import { loadManifest, createFamilyGenerate, createOllamaGenerate } from './phasef-probe.mjs';
import { resolveCrossFamilySeat } from './seat.mjs';
import { FRONTIER_MODEL } from './cross-family-verifier.mjs';

/**
 * The persistent Deep-Think Synthesizer (Wave 5).
 * Reads the shared A1 claim-ledger and generates structured advice based on
 * frontier models (Gemini-primary) or fallback models (Ollama) with Oranges-lens foresight.
 */
export class Synthesizer {
  #manifest;
  #generate;

  /**
   * @param {{manifest?:object, generate?:Function}} [options]
   *   manifest - The parsed tools manifest. If omitted, loaded from default path.
   *   generate - An optional custom/mock generate function (async (prompt) => string).
   */
  constructor({ manifest = null, generate = null } = {}) {
    this.#manifest = manifest;
    this.#generate = generate;
  }

  /**
   * Generates Oranges-lens foresight advice based on the claims currently in the ledger.
   *
   * @param {ClaimLedger} ledger - The shared claim-ledger to read.
   * @param {{env?:object, baseUrl?:string, model?:string}} [options]
   *   env - Environment variables containing API keys (defaults to process.env).
   *   baseUrl - Custom base URL for Ollama fallback.
   *   model - Override model name.
   * @returns {Promise<Readonly<{advice: string, recommendations: readonly string[], anticipations: readonly Array<{future_state_condition: string, enabling_assumption: string}>, timestamp: string}>>}
   */
  async generateAdvice(ledger, options = {}) {
    if (!ledger || typeof ledger.all !== 'function') {
      throw new Error('Synthesizer.generateAdvice requires an A1 ClaimLedger');
    }

    const claims = ledger.all();
    if (claims.length === 0) {
      return Object.freeze({
        advice: 'The ledger is empty. No claims available for synthesis.',
        recommendations: Object.freeze(['Assert a claim to begin mathematical reasoning.']),
        anticipations: Object.freeze([]),
        timestamp: new Date().toISOString(),
      });
    }

    const claimsList = claims
      .map(
        (c) =>
          `- Claim "${c.id}" (${c.type}): "${c.statement}" [Rung: ${c.rung}, Belief: ${c.belief}]`
      )
      .join('\n');

    const prompt = [
      'You are a mathematical reasoning advisor applying Parable-of-the-Oranges foresight.',
      'Analyze the current claim ledger state and identify potential future failures, implicit enabling assumptions, and next steps.',
      'CURRENT CLAIMS IN LEDGER:',
      claimsList,
      'Provide your response in two parts:',
      '1. ADVICE & RECOMMENDATIONS: Bullet points starting with "-" detailing concrete next steps.',
      '2. ORANGES-LENS ANTICIPATIONS: For each potential future issue, specify:',
      '   Future State Condition: [What will go wrong/fail in the future]',
      '   Enabling Assumption: [What underlying assumption makes this possible]',
    ].join('\n');

    let rawAdvice = '';
    const env = options.env || process.env;

    if (typeof this.#generate === 'function') {
      rawAdvice = await this.#generate(prompt);
    } else {
      let manifest;
      try {
        manifest = this.#manifest || loadManifest();
      } catch (err) {
        // Safe fallback if manifest is missing/invalid
        manifest = null;
      }

      if (manifest) {
        // (2026-09-04) the frontier seat is the Anchor dashboard's configured family (seat.mjs), never a
        // hardwired Gemini. The live seams are env-gated by CRUCIBLE_AGENT_LIVE=1, so the fast tier (which
        // never sets it) takes the ollama/mock fallback exactly as before.
        const live = env.CRUCIBLE_AGENT_LIVE === '1';
        if (live) {
          try {
            const seat = await resolveCrossFamilySeat({ manifest, env });
            if (!seat.family) throw new Error(seat.reason);
            const gen = createFamilyGenerate(seat.tool, { env });
            rawAdvice = await gen(prompt);
          } catch (err) {
            rawAdvice = await this.#fallbackToOllama(manifest, prompt, options);
          }
        } else {
          rawAdvice = await this.#fallbackToOllama(manifest, prompt, options);
        }
      } else {
        rawAdvice = this.#getMockAdvice(claims);
      }
    }

    return Object.freeze(this.#parseAdvice(rawAdvice));
  }

  async #fallbackToOllama(manifest, prompt, options) {
    const ollamaSpec = manifest.tools?.ollama || {};
    const modelName = options.model || ollamaSpec.models?.[0]?.name || 'qwen2.5:7b-instruct-q4_K_M';
    const baseUrl = options.baseUrl || ollamaSpec.server?.base_url || 'http://127.0.0.1:11434';
    try {
      const gen = createOllamaGenerate(ollamaSpec, modelName, baseUrl);
      return await gen(prompt);
    } catch (err) {
      return this.#getMockAdvice(options.claims || []);
    }
  }

  #getMockAdvice(claims) {
    const hasUnverified = claims.some((c) => c.belief === 'CONJECTURAL');
    const hasProof = claims.some((c) => c.type === 'proof-bearing');

    let advice = 'Oranges-Lens Foresight Advice:\n';
    advice += '- Verify the unverified claims using the appropriate certifiers.\n';
    if (hasProof) {
      advice += '- Proof-bearing claims must route to out-of-model certifiers (Lean/cross-family).\n';
    }
    advice += '\nOranges-Lens Anticipations:\n';
    if (hasUnverified) {
      advice += 'Future State Condition: Unverified claims are treated as settled by downstream components.\n';
      advice += 'Enabling Assumption: The user ignores the conjectural status and proceeds without greenlighting verification.\n';
    } else {
      advice += 'Future State Condition: Ledger state drifts due to lack of periodic re-verification.\n';
      advice += 'Enabling Assumption: The sticky ledger invariants prevent update verification passes.\n';
    }
    return advice;
  }

  #parseAdvice(raw) {
    const recommendations = [];
    const anticipations = [];

    const lines = raw.split('\n');
    let currentFsc = '';

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (line.startsWith('-') || line.startsWith('*')) {
        recommendations.push(line.replace(/^[-*]\s*/, ''));
      } else if (line.toLowerCase().startsWith('future state condition:')) {
        currentFsc = line.substring(line.indexOf(':') + 1).trim();
      } else if (line.toLowerCase().startsWith('enabling assumption:') && currentFsc) {
        const ea = line.substring(line.indexOf(':') + 1).trim();
        anticipations.push({
          future_state_condition: currentFsc,
          enabling_assumption: ea,
        });
        currentFsc = '';
      }
    }

    // Fallback if no bullet points found
    if (recommendations.length === 0) {
      recommendations.push('Review the current claims in the ledger and prioritize verification.');
    }
    // Fallback if no structured anticipations parsed
    if (anticipations.length === 0) {
      anticipations.push({
        future_state_condition: 'Unanticipated failures in proof verification.',
        enabling_assumption: 'Formal verification pathways are assumed always online and un-quarantined.',
      });
    }

    return {
      advice: raw,
      recommendations: Object.freeze(recommendations),
      anticipations: Object.freeze(anticipations),
      timestamp: new Date().toISOString(),
    };
  }
}
