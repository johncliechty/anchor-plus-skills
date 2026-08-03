import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import {
  runAgent,
  makeRoleRoutedAgent,
  loadModelFamilies,
  familyToDriverName,
} from '../../../trio/drivers/index.mjs';
import { applySeamPass } from '../gandalf/runtime/seam-pass.mjs';
import { createCommissionLedger } from '../gandalf/seam/commission-ledger.mjs';
import {
  runLiveRefutation,
  buildLiveRefuterAgent,
  DEFAULT_REFUTER_ROUTES,
  DRAFTER_FAMILY,
  REFUTER_FAMILY,
  familyFromDriver,
  SelfRefutationHalt,
} from '../gandalf/runtime/live-refuter.mjs';

// Re-export family map for hermetic Gate-3 seating smokes (B3-G3-LITE-SEATING).
export { familyFromDriver };

// 2026-07: the REAL Gandalf protocol, embedded into the commission prompt the way
// Anchor's integration does it — gandalf's SKILL.md is not auto-discoverable by a
// spawned CLI sub-agent, so without this the "RUN Gandalf" instruction made the
// sub-agent IMPROVISE a Gandalf-shaped answer instead of running the protocol.
const _GANDALF_SKILL_MD = path.join(
  path.dirname(fileURLToPath(import.meta.url)), '..', 'gandalf', 'SKILL.md');
const _MAX_PROTOCOL_BYTES = 64 * 1024;
function readGandalfProtocol() {
  try {
    return fs.readFileSync(_GANDALF_SKILL_MD, 'utf8').slice(0, _MAX_PROTOCOL_BYTES);
  } catch {
    return ''; // honest degrade: the commission still runs, minus the embedded protocol
  }
}

/**
 * Persistent Synthesizer Subagent (Intuition & Oversight).
 * Guided by the 'Parable of the Oranges' lens, it oversees the ideation phases,
 * exercises proactive foresight, and injects steering flags into the Tripartite Engine.
 */
export class Synthesizer {
  constructor(options = {}) {
    this.driver = options.driver || null;
    this.runAgent = options.runAgent || null;
    this.history = [];
  }

  /**
   * Receives state updates and runs intuitive oversight to generate steering flags.
   * @param {object} state - Current state of the Tripartite Engine.
   * @returns {Promise<{analysis: string, steeringFlags: string[]}>}
   */
  async update(state) {
    this.history.push(state);

    const systemPrompt = `You are the Jumper Persistent Synthesizer subagent.
Your role is to oversee the ideation process across three phases (Peterson Query, Hesse Glass Bead, Dirac Transfer).
You leverage frontier-model intuition to catch blind spots, synthesize cross-domain connections, and inject "steering flags" into the Tripartite Engine.

CRITICAL INSTRUCTION (The Oranges-Lens / Proactive Foresight):
You are explicitly guided by the Parable of the Oranges. You must exercise deeply contextual foresight.
Do NOT passively watch the frameworks execute or just list literal next steps.
Instead, anticipate the true underlying needs, look 2-3 steps ahead, and identify high-value, non-obvious connections across domains.

When provided with a state update, analyze it and output a set of steering flags.
Steering flags are directives or hints that steer the engine (e.g., suggesting a foreign domain to explore, highlighting a hidden contradiction, or pointing to a deeper systemic need).

You steer, but never decide. You cannot bypass the Tripartite Engine or the Kill-Filter. Keep your steering flags focused on enabling divergent thinking and structural integrity.`;

    // W2 (2026-07-11): send ONLY the immediately-previous state, never the whole
    // accumulated history — each state embeds full gandalfRead/peterson/hesse
    // payloads, so resending `history` compounded token bloat on every update.
    const prevState = this.history.length > 1 ? this.history[this.history.length - 2] : null;
    const prompt = `System Prompt:
${systemPrompt}

Current State of the Ideation Engine:
${JSON.stringify(state, null, 2)}

Previous State (immediately prior phase only — earlier history is not resent):
${JSON.stringify(prevState, null, 2)}

Provide your synthesis and output the steering flags.
Format your output as a JSON object with:
- "analysis": your reasoning and observations using the Parable of the Oranges lens.
- "steeringFlags": an array of strings, each being a steering flag containing non-literal, deep cross-domain guidance or foresight.`;

    const schema = {
      type: "object",
      properties: {
        analysis: { type: "string" },
        steeringFlags: {
          type: "array",
          items: { type: "string" }
        }
      },
      required: ["analysis", "steeringFlags"]
    };

    const customRunAgent = this.runAgent || runAgent;

    const response = await customRunAgent({
      prompt,
      schema,
      driver: this.driver,
      freshContext: true,
      label: "Synthesizer",
      role: "synthesizer"
    });

    return response;
  }
}

// ─── W7 cross-family HALTs ─────────────────────────────────────────────────────
/** Thrown when Jumper's Gate-3 kill-filter verifier would resolve to the DRAFTER/ideation family
 *  (self-review). A NAMED class so a run HALTs honestly instead of a drafter grading its own idea —
 *  a same-family gate shares the generator's blind spots and earns no independent cross-family origin. */
export class JumperSelfReviewHalt extends Error {
  constructor(verifierFamily, drafterFamily, driver) {
    super(
      `Jumper Gate-3 self-review HALT: the adversarial verifier resolves to driver ${JSON.stringify(driver)} ` +
      `(family ${JSON.stringify(verifierFamily)}), which is the DRAFTER/ideation family ${JSON.stringify(drafterFamily)}. ` +
      `Gate 3 MUST run on a NON-drafter family (default driver 'gemini-cli'). Route Gate 3 to a different ` +
      `family (JUMPER_GATE3_DRIVER / options.gate3Driver) or change the drafter driver.`
    );
    this.name = 'JumperSelfReviewHalt';
    this.verifier_family = verifierFamily;
    this.drafter_family = drafterFamily;
    this.driver = driver;
  }
}

/** Thrown when the default cross-family Gate-3 verifier is unreachable (e.g. Gemini/agy down). Jumper
 *  HALTs honestly rather than SILENTLY falling back to a same-family (self-review) gate — down verifier
 *  ⇒ HALT, never Claude self-review (the 5:1 honest-degrade doctrine). */
export class JumperCrossFamilyDegradeHalt extends Error {
  constructor(driver, cause) {
    super(
      `Jumper Gate-3 cross-family HALT: the cross-family verifier (driver ${JSON.stringify(driver)}) was ` +
      `unreachable (${cause?.message ?? cause}). Refusing to fall back to a same-family self-review gate — ` +
      `the run HALTs honestly. Restore the cross-family backend or set JUMPER_GATE3_DRIVER to another ` +
      `non-drafter family.`
    );
    this.name = 'JumperCrossFamilyDegradeHalt';
    this.driver = driver;
    this.cause = cause;
  }
}

/**
 * Production-entry Gate-3 seating resolve (B3-G3 / W5).
 *
 * Same policy KillFilter uses at runtime: coding family → drafter, review family → Gate-3
 * verifier (unless JUMPER_GATE3_DRIVER / options.gate3Driver retargets the driver). LITE may
 * lean ideaRounds but never collapses this independence check.
 *
 * JUMPER_GATE3_DRIVER may retarget the verifier family; it must NEVER invent a
 * skip-independence / self-review mode. An injected gate3Agent is the only explicit
 * allowed override (hermetic tests / independent verifier stub).
 *
 * @param {{
 *   drafterDriver?: string | null,
 *   gate3Driver?: string | null,
 *   gate3Agent?: Function | null,
 *   env?: NodeJS.ProcessEnv,
 *   assertIndependent?: boolean,
 * }} [opts]
 * @returns {{
 *   drafterDriverName: string,
 *   drafterFamily: string,
 *   gate3DriverName: string,
 *   gate3Family: string | null,
 *   hasInjectedAgent: boolean,
 *   independent: boolean,
 *   substrate: string,
 *   prefsCoding: string,
 *   prefsReview: string,
 * }}
 */
export function resolveGate3Seating({
  drafterDriver = null,
  gate3Driver = null,
  gate3Agent = null,
  env = process.env,
  assertIndependent = true,
} = {}) {
  // Prefs: coding family for drafter/default; review family for Gate-3 verifier (unless pinned).
  // Historical 5:1 fallback when registry/prefs unavailable.
  let prefsCoding = 'claude';
  let prefsReview = 'gemini';
  let prefsCodingDriver = 'claude';
  let prefsReviewDriver = 'gemini-cli';
  try {
    const fams = loadModelFamilies(env);
    prefsCoding = fams.coding;
    prefsReview = fams.review;
    prefsCodingDriver = familyToDriverName(fams.coding) || 'claude';
    prefsReviewDriver = familyToDriverName(fams.review) || 'gemini-cli';
  } catch {
    /* registry optional — historical 5:1 fallback above */
  }

  const drafterDriverName = drafterDriver || prefsCodingDriver;
  const drafterFamily = familyFromDriver(drafterDriverName) || prefsCoding;
  // Env/option may retarget the verifier driver; default is review-family (cross-family).
  // No env invents skip-independence — only a different family (or injected agent) is independent.
  const gate3DriverName =
    gate3Driver ?? env?.JUMPER_GATE3_DRIVER ?? prefsReviewDriver;
  const gate3Family = familyFromDriver(gate3DriverName) || prefsReview;
  const hasInjectedAgent = typeof gate3Agent === 'function';
  // Injected agent = explicit allowed override (already an independent verifier surface).
  // Driver seating is independent only when families differ.
  const independent =
    hasInjectedAgent || (!!gate3Family && gate3Family !== drafterFamily);

  const seating = {
    drafterDriverName,
    drafterFamily,
    gate3DriverName,
    gate3Family,
    hasInjectedAgent,
    independent: !!independent,
    substrate: `cross-family:${gate3DriverName}`,
    prefsCoding,
    prefsReview,
  };

  // Self-review guard applies to DRIVER seating (production / gate3Driver / prefs).
  // An injected gate3Agent is already an independent verifier — do not re-litigate
  // prefs coding===review against that injection.
  if (
    assertIndependent &&
    !hasInjectedAgent &&
    (!gate3Family || gate3Family === drafterFamily)
  ) {
    throw new JumperSelfReviewHalt(gate3Family, drafterFamily, gate3DriverName);
  }
  return seating;
}

/**
 * Grade a Gandalf RAW draft through the LIVE cross-family refuter lane (W7) — the mirror of gandalf's
 * `runHostLive`. ONE shared per-run ledger (invariant 1): a live (or injected-stub) Gemini refuter MINTS
 * claim-bound commissions into it, and `applySeamPass` RESOLVES against the SAME ledger, so a genuinely
 * cross-family-refuted, surviving elevation reaches GROUNDED with cross_model:true — DERIVED from the
 * unforgeable ledger, never self-asserted. Honest floor: absent a real refuter, elevations stay
 * SPECULATIVE (never a same-family self-review). Preserves the injected-agent seam (`refuterAgent` /
 * `ledger`) for deterministic tests; a self-review route is a hard HALT.
 *
 * @param {object} rawDraft  the model's raw Gandalf draft ({reasoning, verdict, ..., elevations[]})
 * @param {object} [options] refuterAgent, ledger, refuterRoutes, drafterFamily, refuterFamily, liveRefuter, log
 * @returns {Promise<object>} the conformant advisor output
 */
async function gradeGandalfDraftCrossFamily(rawDraft, options = {}) {
  const elevations = Array.isArray(rawDraft?.elevations) ? rawDraft.elevations : [];
  // Omit refuterRoutes → buildLiveRefuterAgent honors coding/review family prefs.
  const routes = options.refuterRoutes; // undefined unless caller pins
  const drafterFamily = options.drafterFamily; // undefined → prefs CODING_FAMILY
  const refuterFamily = options.refuterFamily || REFUTER_FAMILY;
  // INVARIANT 1 — ONE shared per-run ledger for BOTH the minter and the gate. A split ledger would make
  // every genuine cross-family mint a false negative (the gate can never authenticate an id it did not
  // see minted). `runLiveRefutation` mints into `ledger.mintCommission`; `applySeamPass` resolves via the
  // SAME `ledger.resolveCommission`.
  const ledger = options.ledger || createCommissionLedger();
  const resolveCommission = ledger.resolveCommission;

  // No elevations ⇒ nothing fires the refuter ⇒ a single deterministic grade (single-family floor).
  if (elevations.length === 0) {
    return applySeamPass(rawDraft, { resolveCommission });
  }

  // Resolve the refuter agent: an injected stub (tests) or the live prefs-aware cross-family agent.
  let refuterAgent = options.refuterAgent || null;
  if (!refuterAgent && options.liveRefuter !== false) {
    try {
      refuterAgent = await buildLiveRefuterAgent({ routes, drafterFamily, env: process.env });
    } catch (err) {
      // A self-review route is a HARD HALT (never silently self-review); any other build failure (agy
      // down / transport) honestly degrades to the SPECULATIVE floor below (no false cross-family grant).
      if (err instanceof SelfRefutationHalt) throw err;
      refuterAgent = null;
    }
  }
  if (!refuterAgent) {
    return applySeamPass(rawDraft, { resolveCommission }); // honest floor — no independent refuter ran
  }

  // Dispatch the live/stub refuter; mint claim-bound commissions into the SHARED ledger, then grade the
  // refuted draft against the SAME ledger's resolver — cross_model / GROUNDED are DERIVED here.
  // P1 2026-07-25 (journals 0003/0012): forward the refuter budget — the prereg R=3
  // ceiling HALTed whole tournaments (6 firing elevations > 3) with no dial to turn;
  // standalone gandalf has --budget but the compose seam never passed one through.
  const { draft } = await runLiveRefutation(rawDraft, {
    agent: refuterAgent, ledger, routes, drafterFamily, refuterFamily, log: options.log,
    ...(Number.isInteger(options.refuterBudget) && options.refuterBudget > 0
      ? { budget: options.refuterBudget } : {}),
  });
  return applySeamPass(draft, { resolveCommission });
}

/**
 * Programmatic interface to run the Gandalf skill on a given problem statement or artifact.
 * Prompts the model to generate a RAW draft, then grades it through the LIVE cross-family refuter lane
 * (W7): a Gandalf elevation can reach GROUNDED only via a genuine (Gemini) refutation minted into a
 * shared per-run ledger. Absent a real refuter, elevations honestly floor to SPECULATIVE.
 *
 * @param {string|object} problemState - The problem state or artifact to analyze.
 * @param {object} options - Custom driver / agent runners + refuter injection (useful for testing).
 * @returns {Promise<object>} The conformant advisor output schema.
 */
export async function runGandalf(problemState, options = {}) {
  const driver = options.driver || null;
  const customRunAgent = options.runAgent || runAgent;
  
  const protocol = readGandalfProtocol();
  const prompt = `You are invoking the Gandalf skill as a deep-think advisor lane for Jumper.
RUN the Gandalf protocol below EXACTLY as written (do NOT improvise your own version) over the
problem state/artifact, and return ONLY its RAW draft JSON object per the RAW-DRAFT contract —
do NOT self-assign honesty tiers/stamps (the deterministic seam pass grades those).
${protocol ? `\n=== THE GANDALF PROTOCOL (SKILL.md, verbatim) ===\n${protocol}\n=== END PROTOCOL ===\n` : '\n(protocol file unavailable — follow the RAW-DRAFT contract shape below)\n'}
Problem/Artifact to analyze:
${typeof problemState === 'string' ? problemState : JSON.stringify(problemState, null, 2)}`;

  const response = await customRunAgent({
    prompt,
    schema: {
      type: "object",
      properties: {
        reasoning: { type: "string" },
        verdict: { type: "string" },
        findings: { type: "array" },
        nitpicks: { type: "array" },
        elevations: { type: "array" }
      },
      required: ["reasoning", "verdict", "findings", "nitpicks", "elevations"]
    },
    driver,
    freshContext: true,
    label: "GandalfDraft",
    role: "gandalf"
  });

  // W7: the composed Gandalf deep-think lane inherits the cross-family refuter — a Gandalf elevation
  // can reach GROUNDED only via a genuine (Gemini) refutation minted into a shared per-run ledger.
  return gradeGandalfDraftCrossFamily(response, options);
}

/**
 * Phase 1: Peterson Query (Deconstruction & Probe).
 * Uses the SCAMPER framework to question the current state of the problem,
 * maps anomalous data, and identifies core contradictions from Gandalf's diagnosis.
 */
export class PetersonQuery {
  constructor(options = {}) {
    this.driver = options.driver || null;
    this.runAgent = options.runAgent || null;
  }

  /**
   * Deconstructs the problem using Gandalf's advice and SCAMPER framework.
   * @param {object} gandalfRead - The structured advisor read output from runGandalf.
   * @param {object} [options] - Additional run options, including steeringFlags.
   * @returns {Promise<object>} The deconstructed problem map.
   */
  async run(gandalfRead, options = {}) {
    const steeringFlags = options.steeringFlags || [];
    const customRunAgent = this.runAgent || runAgent;

    const systemPrompt = `You are Jumper Phase 1: Peterson Query (Deconstruction & Probe).
Your role is to deconstruct a problem using the SCAMPER framework, mapping anomalous data, challenging assumptions, and identifying core contradictions.

SCAMPER framework details:
- Substitute: What components, processes, or materials can be replaced?
- Combine: How can this problem/process be combined with other things?
- Adapt: What existing solutions or patterns from other domains can be adapted?
- Modify/Magnify: What elements can be magnified, minimized, or modified?
- Put to another use: How else could we use these constraints/features?
- Eliminate: What can we remove, simplify, or streamline?
- Reverse/Rearrange: What if we reversed the process or rearranged the components?

Analyze the structured Gandalf advisor diagnosis provided. Map any anomalous data points or unverified assumptions, and clearly define at least one core contradiction.`;

    const prompt = `System Prompt:
${systemPrompt}

Structured Gandalf Advisor Read:
${JSON.stringify(gandalfRead, null, 2)}

${steeringFlags.length > 0 ? `Active Steering Flags from Synthesizer:\n${steeringFlags.map(flag => `- ${flag}`).join('\n')}\n` : ''}
Provide your deconstructed problem map.
Format your output as a JSON object with:
- "anomalousData": array of strings mapping anomalous data points, hidden assumptions, or systemic vulnerabilities.
- "scamperAnalysis": object containing deconstruction analysis for each SCAMPER category:
  - "substitute": string
  - "combine": string
  - "adapt": string
  - "modify": string
  - "putToOtherUse": string
  - "eliminate": string
  - "reverse": string
- "coreContradictions": array of objects, each containing:
  - "description": clear description of a core conflict/contradiction (e.g. performance vs safety, statelessness vs durability).
  - "conflictingDemands": summary of the conflicting demands.`;

    const schema = {
      type: "object",
      properties: {
        anomalousData: {
          type: "array",
          items: { type: "string" }
        },
        scamperAnalysis: {
          type: "object",
          properties: {
            substitute: { type: "string" },
            combine: { type: "string" },
            adapt: { type: "string" },
            modify: { type: "string" },
            putToOtherUse: { type: "string" },
            eliminate: { type: "string" },
            reverse: { type: "string" }
          },
          required: ["substitute", "combine", "adapt", "modify", "putToOtherUse", "eliminate", "reverse"]
        },
        coreContradictions: {
          type: "array",
          items: {
            type: "object",
            properties: {
              description: { type: "string" },
              conflictingDemands: { type: "string" }
            },
            required: ["description", "conflictingDemands"]
          }
        }
      },
      required: ["anomalousData", "scamperAnalysis", "coreContradictions"]
    };

    const response = await customRunAgent({
      prompt,
      schema,
      driver: options.driver || this.driver,
      freshContext: true,
      label: "PetersonQuery",
      role: "deconstruct"
    });

    return response;
  }
}

export async function petersonQuery(gandalfRead, options = {}) {
  const query = new PetersonQuery(options);
  return query.run(gandalfRead, options);
}

/**
 * Phase 2: Hesse Glass Bead (Analogical Transfer).
 * Maps the Peterson Query deconstructed problem map onto a completely foreign domain structure.
 */
export class HesseGlassBead {
  constructor(options = {}) {
    this.driver = options.driver || null;
    this.runAgent = options.runAgent || null;
  }

  /**
   * Maps the Peterson Query deconstructed problem map onto a foreign domain structure.
   * @param {object} problemMap - The deconstructed problem map from PetersonQuery.
   * @param {object} [options] - Additional run options, including steeringFlags.
   * @returns {Promise<object>} The analogical mapping.
   */
  async run(problemMap, options = {}) {
    const steeringFlags = options.steeringFlags || [];
    const customRunAgent = this.runAgent || runAgent;

    const systemPrompt = `You are Jumper Phase 2: Hesse Glass Bead (Analogical Transfer).
Your role is to map a deconstructed problem map onto a completely foreign domain structure (e.g., mapping a software issue to a biological system, Renaissance art, music theory, or geological formations) to facilitate lateral, analogical thinking.

You must maintain structural integrity: ensure that the relationships, elements, and core contradictions in the original domain map logically and accurately onto the target foreign domain.

Analyze the deconstructed problem map provided (which includes anomalous data points, SCAMPER analysis, and core contradictions) and construct an analogical mapping.`;

    const prompt = `System Prompt:
${systemPrompt}

Deconstructed Problem Map:
${JSON.stringify(problemMap, null, 2)}

${steeringFlags.length > 0 ? `Active Steering Flags from Synthesizer:\n${steeringFlags.map(flag => `- ${flag}`).join('\n')}\n` : ''}
Provide your analogical mapping.
Format your output as a JSON object with:
- "foreignDomain": name of the target domain (e.g. "Renaissance Fresco Painting Techniques", "Biological Cell Membrane Structures", etc.).
- "analogyReasoning": detailed explanation of how this domain abstraction is relevant and how it helps reframe the problem.
- "structuralMapping": array of objects, each containing:
  - "originalElement": the element or relationship from the source problem/system.
  - "foreignElement": the corresponding element or relationship in the target foreign domain.
  - "mappingRationale": explanation of the structural similarity.
- "mappedContradictions": array of objects, each containing:
  - "originalContradiction": the contradiction description from the original problem.
  - "foreignContradiction": the corresponding contradiction expressed in the terms/constraints of the foreign domain.
  - "structuralParallel": explanation of why they share the same underlying structure.`;

    const schema = {
      type: "object",
      properties: {
        foreignDomain: { type: "string" },
        analogyReasoning: { type: "string" },
        structuralMapping: {
          type: "array",
          items: {
            type: "object",
            properties: {
              originalElement: { type: "string" },
              foreignElement: { type: "string" },
              mappingRationale: { type: "string" }
            },
            required: ["originalElement", "foreignElement", "mappingRationale"]
          }
        },
        mappedContradictions: {
          type: "array",
          items: {
            type: "object",
            properties: {
              originalContradiction: { type: "string" },
              foreignContradiction: { type: "string" },
              structuralParallel: { type: "string" }
            },
            required: ["originalContradiction", "foreignContradiction", "structuralParallel"]
          }
        }
      },
      required: ["foreignDomain", "analogyReasoning", "structuralMapping", "mappedContradictions"]
    };

    const response = await customRunAgent({
      prompt,
      schema,
      driver: options.driver || this.driver,
      freshContext: true,
      label: "HesseGlassBead",
      role: "analogy"
    });

    return response;
  }
}

export async function hesseGlassBead(problemMap, options = {}) {
  const bead = new HesseGlassBead(options);
  return bead.run(problemMap, options);
}

/**
 * Phase 3: Dirac Transfer (TRIZ Symmetry).
 * Uses TRIZ principles of invention to resolve the contradictions identified in Phase 1,
 * using the analogical insights generated in Phase 2.
 */
export class DiracTransfer {
  constructor(options = {}) {
    this.driver = options.driver || null;
    this.runAgent = options.runAgent || null;
  }

  /**
   * Resolves the contradictions using TRIZ principles and the analogical insights.
   * @param {object} analogicalMapping - The analogical mapping from HesseGlassBead.
   * @param {array|object} [coreContradictionsOrOptions] - Core contradictions or options.
   * @param {object} [options] - Additional run options, including steeringFlags.
   * @returns {Promise<object>} The structurally elegant resolution.
   */
  async run(analogicalMapping, coreContradictionsOrOptions = {}, options = {}) {
    let coreContradictions = [];
    let runOptions = {};
    if (Array.isArray(coreContradictionsOrOptions)) {
      coreContradictions = coreContradictionsOrOptions;
      runOptions = options;
    } else {
      runOptions = { ...coreContradictionsOrOptions, ...options };
      coreContradictions = runOptions.coreContradictions || [];
    }

    const steeringFlags = runOptions.steeringFlags || [];
    const customRunAgent = this.runAgent || runAgent;

    const systemPrompt = `You are Jumper Phase 3: Dirac Transfer (Symmetry & Resolution).
Your role is to resolve the contradictions using TRIZ principles and the analogical insights from Phase 2.

TRIZ principles details:
TRIZ (Theory of Inventive Problem Solving) provides 40 principles to resolve physical and technical contradictions without compromise. Examples include:
- Segmentation (dividing an object/system into independent parts)
- Asymmetry (changing the shape or design to be asymmetrical)
- Merging/Consolidation (bringing identical or similar objects closer)
- Universality (making a part perform multiple functions)
- Nested Doll / Matryoshka (one object inside another)
- 'The other way round' (inverting the action or process)
- Dynamicity (allowing characteristics to change for optimal performance)
- Feedback (introducing control/feedback loops)
- Intermediary/Mediator (using an intermediate carrier or process)
- Discarding and recovering (making elements disappear or regenerate)

Analyze the analogical mapping (which includes foreignDomain, analogyReasoning, structuralMapping, and mappedContradictions) and any provided core contradictions. Output a structurally elegant resolution mapped back to the original domain.`;

    const prompt = `System Prompt:
${systemPrompt}

Analogical Mapping from Phase 2:
${JSON.stringify(analogicalMapping, null, 2)}

Core Contradictions:
${JSON.stringify(coreContradictions, null, 2)}

${steeringFlags.length > 0 ? `Active Steering Flags from Synthesizer:\n${steeringFlags.map(flag => `- ${flag}`).join('\n')}\n` : ''}
Provide your symmetrical resolution.
Format your output as a JSON object with:
- "trizPrinciplesApplied": array of strings listing the TRIZ principles applied (e.g. ["Segmentation", "Feedback"]).
- "analogicalResolution": description of how the contradiction was resolved within the foreign analogical domain.
- "symmetricalResolution": the elegant solution mapped back to the original domain, resolving the core contradictions.
- "resolutionReasoning": the technical or structural reasoning explaining how the resolution achieves symmetry and resolves the contradictions without compromise.`;

    const schema = {
      type: "object",
      properties: {
        trizPrinciplesApplied: {
          type: "array",
          items: { type: "string" }
        },
        analogicalResolution: { type: "string" },
        symmetricalResolution: { type: "string" },
        resolutionReasoning: { type: "string" }
      },
      required: ["trizPrinciplesApplied", "analogicalResolution", "symmetricalResolution", "resolutionReasoning"]
    };

    const response = await customRunAgent({
      prompt,
      schema,
      driver: runOptions.driver || this.driver,
      freshContext: true,
      label: "DiracTransfer",
      role: "triz"
    });

    return response;
  }
}

export async function diracTransfer(analogicalMapping, coreContradictionsOrOptions = {}, options = {}) {
  let ctorOptions = {};
  if (Array.isArray(coreContradictionsOrOptions)) {
    ctorOptions = options;
  } else {
    ctorOptions = { ...coreContradictionsOrOptions, ...options };
  }
  const transfer = new DiracTransfer(ctorOptions);
  return transfer.run(analogicalMapping, coreContradictionsOrOptions, options);
}

/**
 * The 3-Gate Kill-Filter (Anti-Hallucination Guardrails).
 * Every generated idea must survive three gates:
 * 1. Existence Proof
 * 2. Glass Bead Syntax Test
 * 3. Dirac Structural Symmetry Test (Adversarial Gate)
 *
 * B3 Decision A (load-bearing): when `killGates` is supplied (depth-locked path),
 * happy-path stage count (gateLogs length on full pass) MUST equal knobs.killGates.
 * Never silently thin stages below the resolved floor.
 */
export class KillFilter {
  constructor(options = {}) {
    this.driver = options.driver || null;
    this.runAgent = options.runAgent || null;
    /** @type {number | null} expected stage count from depth knobs (Decision A) */
    this.killGates = Number.isInteger(options.killGates) ? options.killGates : null;
  }

  /**
   * Runs the 3-Gate Kill-Filter on the concept/solution.
   * If any gate fails, the concept is rejected and logged.
   *
   * @param {object} concept - The concept/solution to test.
   * @param {object} [options] - Additional runtime options, including driver + killGates.
   * @returns {Promise<object>} The filter result.
   */
  async run(concept, options = {}) {
    const runOptions = { ...options };
    const customRunAgent = this.runAgent || runAgent;
    const driver = runOptions.driver || this.driver;
    // Decision A: expected stage count from depth-locked knobs (CLI passes killGates).
    const expectedKillGates = Number.isInteger(runOptions.killGates)
      ? runOptions.killGates
      : (Number.isInteger(this.killGates) ? this.killGates : 3);
    const gateLogs = [];

    // --- GATES 1+2: ONE MERGED CALL (W2, 2026-07-11) ---
    // Both are same-family cheap pre-filters over the SAME concept (existence proof;
    // analogy integrity) and were two strictly-sequential calls. One call, two
    // independently-judged verdicts in the schema — the gateLogs shape, the
    // failedAtGate attribution (1 before 2), and the short-circuit BEFORE the
    // cross-family Gate 3 are all unchanged. Saves 1 call + 1 sequential round per
    // candidate (×N in portfolio mode).
    const hasMapping = concept.analogicalMapping && typeof concept.analogicalMapping === 'object' &&
      Object.keys(concept.analogicalMapping).length > 0;

    const systemPromptGate12 = `You are Jumper Kill-Filter Gates 1+2 (one pass, two INDEPENDENT verdicts).
GATE 1 — Existence Proof: verify the concept is theoretically possible and does not violate the fundamental axioms or laws of its target domain (impossible physics, non-existent APIs, contradictory requirements ⇒ reject gate 1).
GATE 2 — Glass Bead Syntax Test: evaluate whether the analogical mapping holds logical and structural integrity, or is merely a forced, shallow metaphor (elements/relationships/contradictions must map logically to the foreign domain's constraints).
Judge each gate ON ITS OWN MERITS — a concept may pass one and fail the other.`;

    const promptGate12 = `System Prompt:
${systemPromptGate12}

Concept to evaluate:
Symmetrical Resolution: ${concept.symmetricalResolution || ''}
Resolution Reasoning: ${concept.resolutionReasoning || ''}

Analogical Mapping:
${hasMapping ? JSON.stringify(concept.analogicalMapping, null, 2) : '(missing — gate 2 auto-fails deterministically; judge gate 1 only)'}

Core Contradictions:
${JSON.stringify(concept.coreContradictions || [], null, 2)}

Format your output as a JSON object with:
- "gate1": { "passed": boolean, "reasoning": string }  (existence proof)
- "gate2": { "passed": boolean, "reasoning": string }  (analogy integrity${hasMapping ? '' : ' — mapping missing, return passed:false'})`;

    const gateVerdict = {
      type: "object",
      properties: { passed: { type: "boolean" }, reasoning: { type: "string" } },
      required: ["passed", "reasoning"]
    };
    const schemaGate12 = {
      type: "object",
      properties: { gate1: gateVerdict, gate2: gateVerdict },
      required: ["gate1", "gate2"]
    };

    const res12 = await customRunAgent({
      prompt: promptGate12,
      schema: schemaGate12,
      driver,
      freshContext: true,
      label: "KillFilterGate1and2",
      role: "gate"
    });
    const res1 = res12?.gate1 ?? { passed: false, reasoning: "Gate 1 verdict missing from the merged reply." };
    // The missing-mapping fail stays DETERMINISTIC — never delegated to the model.
    const res2 = hasMapping
      ? (res12?.gate2 ?? { passed: false, reasoning: "Gate 2 verdict missing from the merged reply." })
      : { passed: false, reasoning: "Gate 2 failed: analogical mapping is missing or invalid." };

    gateLogs.push({ gate: 1, name: "Existence Proof", passed: res1.passed, reasoning: res1.reasoning });
    if (!res1.passed) {
      return { passed: false, failedAtGate: 1, rejectionReason: res1.reasoning, gateLogs };
    }

    gateLogs.push({ gate: 2, name: "Glass Bead Syntax Test", passed: res2.passed, reasoning: res2.reasoning });
    if (!res2.passed) {
      return { passed: false, failedAtGate: 2, rejectionReason: res2.reasoning, gateLogs };
    }

    // --- GATE 3: DIRAC STRUCTURAL SYMMETRY TEST (ADVERSARIAL GATE) ---
    const systemPromptGate3 = `You are Jumper Kill-Filter Gate 3: Dirac Structural Symmetry Test (Adversarial Subagent).
Your sole purpose is to act as an independent, highly critical adversary. You must actively hunt for LLM hallucinations, logical gaps, hand-waving, unstated assumptions, and structural asymmetries in the proposed resolution.
Be ruthless. Reject any concept that contains vague steps, unresolved contradictions, or is not practically applicable. Only let concepts pass if they are structurally sound, concrete, and viable.
Specifically, evaluate the structural symmetry of the resolution and check for unresolved contradictions by comparing it against the original core contradictions and the analogical mappings.`;

    const promptGate3 = `System Prompt:
${systemPromptGate3}

Concept to evaluate:
Symmetrical Resolution: ${concept.symmetricalResolution || ''}
Resolution Reasoning: ${concept.resolutionReasoning || ''}
Triz Principles Applied: ${JSON.stringify(concept.trizPrinciplesApplied || [])}

Core Contradictions:
${JSON.stringify(concept.coreContradictions || [])}

Analogical Mapping:
${JSON.stringify(concept.analogicalMapping || {})}

Evaluate this resolved concept. Actively look for logic gaps, hallucinated APIs/technologies, asymmetry, or practical applicability issues.
Format your output as a JSON object with:
- "passed": boolean (true only if you verify the concept is structurally sound, complete, and practically applicable without logic gaps or hallucinations; false if you identify any blocker or gap).
- "reasoning": detailed explanation of your finding, explicitly calling out any logic gaps, hallucinations, or reasons for rejection.`;

    const schemaGate3 = {
      type: "object",
      properties: {
        passed: { type: "boolean" },
        reasoning: { type: "string" }
      },
      required: ["passed", "reasoning"]
    };

    // 2026-07 (W7) + B3 W5: Gate 3 is the ADVERSARIAL gate — real independence means a DIFFERENT
    // model family by DEFAULT, not opt-in. Production seating is resolveGate3Seating (prefs → driver;
    // JUMPER_GATE3_DRIVER may retarget family but never invent skip-independence). LITE depth lock
    // may lean ideaRounds but never collapses this check. Self-review → JumperSelfReviewHalt;
    // down cross-family backend → JumperCrossFamilyDegradeHalt (never silent self-review).
    const seating = resolveGate3Seating({
      drafterDriver: driver || null,
      gate3Driver: runOptions.gate3Driver ?? null,
      gate3Agent: runOptions.gate3Agent ?? null,
      env: runOptions.env || process.env,
      assertIndependent: true,
    });
    const { gate3DriverName, drafterDriverName, substrate: gate3Substrate } = seating;

    // The verifier agent: an injected role-routed stub (tests) wins; else, when a custom runAgent seam
    // is injected, route Gate 3 through it with the cross-family driver (keeps deterministic tests in
    // control); else (production default) build a real role-routed agent that sends Gate 3 to Gemini.
    let res3;
    try {
      if (runOptions.gate3Agent) {
        res3 = await runOptions.gate3Agent(promptGate3, { role: "gate", label: "KillFilterGate3", schema: schemaGate3 });
      } else if (customRunAgent !== runAgent) {
        res3 = await customRunAgent({
          prompt: promptGate3,
          schema: schemaGate3,
          driver: gate3DriverName,
          freshContext: true,
          label: "KillFilterGate3",
          role: "gate"
        });
      } else {
        const gate3Agent = makeRoleRoutedAgent({
          routes: {
            gate: { driver: gate3DriverName, model: runOptions.gate3Model ?? null },
            default: { driver: drafterDriverName },
          },
        });
        res3 = await gate3Agent(promptGate3, { role: "gate", label: "KillFilterGate3", schema: schemaGate3 });
      }
    } catch (err) {
      if (err instanceof JumperSelfReviewHalt || err instanceof SelfRefutationHalt) throw err;
      // Down cross-family verifier ⇒ HALT honestly (never a same-family self-review fallback).
      throw new JumperCrossFamilyDegradeHalt(gate3DriverName, err);
    }

    gateLogs.push({
      gate: 3,
      name: "Dirac Structural Symmetry Test",
      substrate: gate3Substrate,
      passed: res3.passed,
      reasoning: res3.reasoning
    });

    if (!res3.passed) {
      return {
        passed: false,
        failedAtGate: 3,
        rejectionReason: res3.reasoning,
        gateLogs,
        stageCount: gateLogs.length,
        killGates: expectedKillGates,
      };
    }

    // Happy path: Decision A — stage count must equal knobs.killGates (never thin).
    const stageCount = gateLogs.length;
    if (stageCount !== expectedKillGates) {
      return {
        passed: false,
        failedAtGate: null,
        rejectionReason:
          `Kill-filter stage count ${stageCount} !== knobs.killGates ${expectedKillGates} ` +
          `(Decision A: never thin kill stages)`,
        gateLogs,
        stageCount,
        killGates: expectedKillGates,
      };
    }

    return {
      passed: true,
      failedAtGate: null,
      rejectionReason: null,
      gateLogs,
      stageCount,
      killGates: expectedKillGates,
    };
  }
}

export async function killFilter(concept, options = {}) {
  const filter = new KillFilter(options);
  return filter.run(concept, options);
}

/**
 * Jumper Brainstorming Engine.
 * Integrates PetersonQuery, HesseGlassBead, DiracTransfer, Synthesizer, and KillFilter.
 */
export class Jumper {
  constructor(options = {}) {
    this.driver = options.driver || null;
    this.runAgent = options.runAgent || null;
  }

  /**
   * Runs the complete ideation pipeline and generates a Grounding Execution Protocol.
   *
   * 2026-07 portfolio mode: pass `fanOut: N` (N ≥ 2) to generate N analogical
   * mappings (sphere-diversified, concurrent), one TRIZ resolution per mapping,
   * and run the Kill-Filter as a TOURNAMENT — the result then carries
   * `survivors[]` (ranked, GEP attached to the top one) + `killLog[]` instead of
   * a single take-it-or-leave-it concept. `retryOnKill: true` additionally
   * replays phases 2-3 ONCE with the rejection reasons injected as steering
   * flags when everything died. Default (`fanOut` absent/1) is the historical
   * single-candidate pipeline, unchanged.
   *
   * @param {string|object} problemState - Initial problem statement/intent.
   * @param {object} [options] - Options (driver, runAgent, fanOut, retryOnKill, gate3Driver).
   * @returns {Promise<object>} Pipeline execution results.
   */
  async run(problemState, options = {}) {
    const runOptions = { ...options };
    const customRunAgent = runOptions.runAgent || this.runAgent || runAgent;
    const driver = runOptions.driver || this.driver;
    // W2 (2026-07-11): the PORTFOLIO is the default — NORTH-STAR.md:7 promises "a
    // portfolio … not a single take-it-or-leave-it idea", and fan-out costs only ~2
    // extra sequential rounds (branches parallelize). Explicit `fanOut: 1` selects
    // the legacy single-candidate pipeline.
    const fanOut = runOptions.fanOut === 1 ? 1
      : Number.isInteger(runOptions.fanOut) && runOptions.fanOut > 1 ? Math.min(runOptions.fanOut, 5)
      : 3;

    const synthesizer = new Synthesizer({ driver, runAgent: customRunAgent });

    // P1 2026-07-25 (journals 0005/0004/0007/0011/0014): stage heartbeats. Sparse
    // logging made a healthy long run indistinguishable from a hang and caused a
    // false-DONE by the cadence agent. `options.log` is the sink (CLI wires stderr).
    const hb = typeof runOptions.log === 'function' ? runOptions.log : () => {};

    // Step 1: Run Gandalf to get structured advice. Thread the run options through so the composed
    // deep-think lane inherits the cross-family refuter injection (refuterAgent/ledger/routes) too (W7).
    hb('jumper: gandalf:start');
    const gandalfRead = await runGandalf(problemState, { ...runOptions, driver, runAgent: customRunAgent });
    hb('jumper: gandalf:done');

    // Step 2: Update synthesizer and get steering flags
    const synth1 = await synthesizer.update({
      problem: problemState,
      currentPhase: 'Peterson Query (Input)',
      gandalfRead
    });
    const flags1 = synth1?.steeringFlags || [];

    // Step 3: Run Phase 1 - Peterson Query
    const queryEngine = new PetersonQuery({ driver, runAgent: customRunAgent });
    const petersonResult = await queryEngine.run(gandalfRead, { ...runOptions, steeringFlags: flags1 });

    // Step 4: Update synthesizer and get steering flags for Phase 2
    const synth2 = await synthesizer.update({
      problem: problemState,
      currentPhase: 'Hesse Glass Bead (Input)',
      problemMap: petersonResult
    });
    // W2: flags carry only the CURRENT round's steering (flags1 already steered
    // Peterson; re-accumulating them inflated every downstream prompt for no lift).
    const flags2 = synth2?.steeringFlags || [];

    const beadEngine = new HesseGlassBead({ driver, runAgent: customRunAgent });
    const transferEngine = new DiracTransfer({ driver, runAgent: customRunAgent });
    // B3 W3: thread killGates from depth-locked CLI so Decision A stage count can match knobs.
    const filterEngine = new KillFilter({
      driver,
      runAgent: customRunAgent,
      killGates: Number.isInteger(runOptions.killGates) ? runOptions.killGates : undefined,
    });

    // Sphere hints force GENUINE domain diversity across the fan-out (each
    // sibling is blind to the others, so diversity is assigned, not hoped for).
    const SPHERES = [
      'the natural sciences (biology, physics, chemistry, geology, ecology)',
      'the arts and humanities (music theory, architecture, painting, literature, history)',
      'social/rule systems (economics, law, games, logistics, ritual)',
      'engineered physical systems (mechanics, materials, civil/aero/naval engineering)',
      'information/communication systems outside software (linguistics, cryptography history, signalling)',
    ];

    // One candidate = hesse (with an optional sphere hint) -> [synthesizer] -> dirac -> concept.
    // W2 (2026-07-11): the per-candidate Synthesizer interlude runs ONLY on the legacy
    // single-candidate path (no sphere hint). In fan-out it is DROPPED: (a) the sphere
    // hint already does the steering that call existed for; (b) all N parallel
    // candidates shared ONE Synthesizer whose history mixed sibling states into every
    // prompt — nondeterministic sibling contamination that broke the "each sibling is
    // blind to the others" invariant; (c) it was 1 sequential call per candidate.
    const buildCandidate = async (sphereHint, extraFlags = []) => {
      const hesseFlags = [...flags2, ...extraFlags,
        ...(sphereHint ? [`Choose your foreign domain from ${sphereHint} — sibling candidates cover other spheres; do not stray from yours.`] : [])];
      const hesseResult = await beadEngine.run(petersonResult, { ...runOptions, steeringFlags: hesseFlags });
      let flags3 = extraFlags;
      if (!sphereHint) {
        const synth3 = await synthesizer.update({
          problem: problemState,
          currentPhase: 'Dirac Transfer (Input)',
          analogicalMapping: hesseResult
        });
        flags3 = [...(synth3?.steeringFlags || []), ...extraFlags];
      }
      const diracResult = await transferEngine.run(hesseResult, petersonResult.coreContradictions, { ...runOptions, steeringFlags: flags3 });
      return {
        ...diracResult,
        analogicalMapping: hesseResult,
        coreContradictions: petersonResult.coreContradictions
      };
    };

    // ---- PORTFOLIO MODE (fanOut > 1): tournament over N candidates ----
    if (fanOut > 1) {
      const runTournament = async (extraFlags = []) => {
        const candidates = await Promise.all(
          Array.from({ length: fanOut }, (_, i) => {
            hb(`jumper: sphere:${i + 1}/${fanOut} candidate start`);
            return buildCandidate(SPHERES[i % SPHERES.length], extraFlags)
              .then((c) => { hb(`jumper: sphere:${i + 1}/${fanOut} candidate built (${c?.analogicalMapping?.foreignDomain ?? '?'})`); return c; });
          }));
        const judged = await Promise.all(candidates.map(async (concept, i) => {
          hb(`jumper: killfilter:candidate ${i + 1}/${candidates.length} start`);
          const filter = await filterEngine.run(concept, runOptions);
          hb(`jumper: killfilter:candidate ${i + 1}/${candidates.length} ${filter.passed ? 'PASSED all gates' : `KILLED at gate ${filter.failedAtGate}`}`);
          return { concept, filter };
        }));
        return {
          survivors: judged.filter((j) => j.filter.passed),
          killed: judged.filter((j) => !j.filter.passed),
        };
      };

      let { survivors, killed } = await runTournament();
      let retried = false;
      if (!survivors.length && runOptions.retryOnKill) {
        // One bounded retry: the rejections become steering flags (the loop
        // learns WHY everything died before trying again). Never more than once.
        retried = true;
        const lessons = killed.map((k) => `A prior candidate was KILLED at gate ${k.filter.failedAtGate}: ${String(k.filter.rejectionReason || '').slice(0, 300)}`);
        ({ survivors, killed } = await runTournament(lessons));
      }

      const killLog = killed.map((k) => ({
        failedAtGate: k.filter.failedAtGate,
        rejectionReason: k.filter.rejectionReason,
        gateLogs: k.filter.gateLogs,
        foreignDomain: k.concept?.analogicalMapping?.foreignDomain ?? null,
      }));

      if (!survivors.length) {
        return { passed: false, fanOut, retried, survivors: [], killLog };
      }

      // Rank: all survivors passed all 3 gates; order by richer structural
      // mappings first (a deeper analogy is the better raw material).
      survivors.sort((a, b) =>
        (b.concept?.analogicalMapping?.structuralMapping?.length ?? 0) -
        (a.concept?.analogicalMapping?.structuralMapping?.length ?? 0));
      const top = survivors[0];
      const gep = await this._generateGEP(top.concept, customRunAgent, driver);
      return {
        passed: true,
        fanOut,
        retried,
        concept: top.concept,
        gateLogs: top.filter.gateLogs,
        groundingExecutionProtocol: gep,
        survivors: survivors.map((s, i) => ({
          rank: i + 1,
          foreignDomain: s.concept?.analogicalMapping?.foreignDomain ?? null,
          concept: s.concept,
          gateLogs: s.filter.gateLogs,
        })),
        killLog,
      };
    }

    // ---- LEGACY SINGLE-CANDIDATE PATH (fanOut = 1; unchanged behavior) ----
    const concept = await buildCandidate(null);
    const filterResult = await filterEngine.run(concept, runOptions);

    if (!filterResult.passed) {
      if (runOptions.retryOnKill) {
        const lesson = `A prior candidate was KILLED at gate ${filterResult.failedAtGate}: ${String(filterResult.rejectionReason || '').slice(0, 300)}`;
        const concept2 = await buildCandidate(null, [lesson]);
        const filter2 = await filterEngine.run(concept2, runOptions);
        if (filter2.passed) {
          const gep2 = await this._generateGEP(concept2, customRunAgent, driver);
          return { passed: true, retried: true, concept: concept2, gateLogs: filter2.gateLogs, groundingExecutionProtocol: gep2 };
        }
      }
      return {
        passed: false,
        failedAtGate: filterResult.failedAtGate,
        rejectionReason: filterResult.rejectionReason,
        gateLogs: filterResult.gateLogs,
        concept
      };
    }

    // Step 9: Format the output into the Grounding Execution Protocol
    const gepResult = await this._generateGEP(concept, customRunAgent, driver);

    return {
      passed: true,
      concept,
      gateLogs: filterResult.gateLogs,
      groundingExecutionProtocol: gepResult
    };
  }

  /** Grounding Execution Protocol generation (shared by both pipeline modes). */
  async _generateGEP(concept, customRunAgent, driver) {
    const systemPromptGEP = `You are Jumper Grounding Execution Protocol Generator.
Your role is to format the approved symmetrical resolution into a Grounding Execution Protocol: a concrete, step-by-step test plan to validate the idea in reality.

Determine the domain type (e.g., software, empirical/scientific, art/philosophy) and output:
1. For Software/Engineering: A proof-of-concept architecture, unit test definitions, or a minimal viable implementation plan.
2. For Empirical/Scientific: A formal experiment design, defined variables, and success metrics.
3. For Art/Philosophy: A concrete phenomenological demonstration, a rigorous logical proof, or a specific creative output.

Ensure the steps are concrete, verifiable, and directly test the generated idea.`;

    const promptGEP = `System Prompt:
${systemPromptGEP}

Approved Concept:
Symmetrical Resolution: ${concept.symmetricalResolution}
Resolution Reasoning: ${concept.resolutionReasoning}
TRIZ Principles Applied: ${JSON.stringify(concept.trizPrinciplesApplied || [])}
Analogical Mapping from Hesse Glass Bead:
${JSON.stringify(concept.analogicalMapping, null, 2)}

Generate the Grounding Execution Protocol to validate this resolution.`;

    const schemaGEP = {
      type: "object",
      properties: {
        domainType: { type: "string" },
        validationSetup: { type: "string" },
        concreteSteps: {
          type: "array",
          items: {
            type: "object",
            properties: {
              stepNumber: { type: "integer" },
              description: { type: "string" },
              verificationMethod: { type: "string" }
            },
            required: ["stepNumber", "description", "verificationMethod"]
          }
        },
        successMetrics: {
          type: "array",
          items: { type: "string" }
        },
        risksAndMitigations: {
          type: "array",
          items: { type: "string" }
        }
      },
      required: ["domainType", "validationSetup", "concreteSteps", "successMetrics", "risksAndMitigations"]
    };

    return customRunAgent({
      prompt: promptGEP,
      schema: schemaGEP,
      driver,
      freshContext: true,
      label: "GroundingExecutionProtocol",
      role: "ground"
    });
  }
}

export async function jumper(problemState, options = {}) {
  const engine = new Jumper(options);
  return engine.run(problemState, options);
}


