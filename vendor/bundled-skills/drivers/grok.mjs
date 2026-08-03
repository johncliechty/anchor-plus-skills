// drivers/grok.mjs — the Grok (xAI) model backend behind the trio `runAgent` seam.
//
// xAI's Chat Completions API is OpenAI-compatible, so this driver reuses the shared
// OpenAI-compatible request/response shaping (`_openai-compat.mjs`) — only the base
// URL (`api.x.ai`), the default model, and the key var (`XAI_API_KEY`) differ.
//
// Capability profile: NOT sub-agent-capable (raw HTTP API); structured output is
// NATIVE via the OpenAI-compatible `response_format`, parsed/validated by the shared
// seam (retry-once-then-ABSTAIN). Selected via `TRIO_DRIVER=grok`. With no key and
// no injected transport it HALTs rather than firing a keyless request, so the live
// smoke test SKIPS when the key is absent — it never fails.

import { runWithSchema } from './_seam.mjs';
import { makeChatTransport } from './_openai-compat.mjs';

export const GROK_BASE_URL = 'https://api.x.ai/v1';
export const DEFAULT_GROK_MODEL = 'grok-2-latest';

/**
 * Build the Grok transport over the OpenAI-compatible xAI endpoint. Reads the
 * key/model from `opts` then env (`XAI_MODEL`/`GROK_MODEL`), defaulting the model to
 * {@link DEFAULT_GROK_MODEL}. Inject `fetchImpl` in tests.
 */
export function makeGrokTransport({ env = process.env, model, apiKey, fetchImpl, log } = {}) {
  return makeChatTransport({
    baseUrl: GROK_BASE_URL,
    apiKey: apiKey ?? env.XAI_API_KEY,
    model: model ?? env.XAI_MODEL ?? env.GROK_MODEL ?? DEFAULT_GROK_MODEL,
    fetchImpl,
    keyName: 'XAI_API_KEY',
    log,
  });
}

/**
 * The Grok registry entry.
 * @type {{ name:string, subAgentCapable:boolean, structuredOutput:string,
 *          runAgent:(opts?:object)=>Promise<any> }}
 */
export const grokDriver = {
  name: 'grok',
  subAgentCapable: false,
  structuredOutput: 'json-mode (OpenAI-compatible response_format)',
  async runAgent(opts = {}) {
    const { prompt, schema, label, log } = opts;
    const transport = makeGrokTransport(opts);
    return runWithSchema({ transport, prompt, schema, label, log });
  },
};

export default grokDriver;
