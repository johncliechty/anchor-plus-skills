// drivers/openai.mjs — the OpenAI model backend behind the trio `runAgent` seam.
//
// Capability profile: NOT sub-agent-capable (a raw HTTP API spawns no fresh CLI
// context); `freshContext` is approximated by each call being an independent,
// stateless request — exactly researchPrime's "clean isolated call" model.
// Structured output is NATIVE: when a `schema` is supplied the request asks for
// JSON mode (`response_format: json_schema`), and the shared seam parses/validates
// with retry-once-then-ABSTAIN so behavior matches every other backend.
//
// Selected via `TRIO_DRIVER=openai` (or `runAgent({ driver:'openai', ... })`). The
// key lives in `OPENAI_API_KEY` (collaborator env, never committed). With no key
// and no injected transport the driver HALTs rather than firing a keyless request,
// so the live smoke test SKIPS when the key is absent — it never fails.

import { runWithSchema } from './_seam.mjs';
import { makeChatTransport } from './_openai-compat.mjs';

export const OPENAI_BASE_URL = 'https://api.openai.com/v1';
export const DEFAULT_OPENAI_MODEL = 'gpt-4o';

/**
 * Build the OpenAI transport. Reads the key/model from `opts` then env, defaulting
 * the model to {@link DEFAULT_OPENAI_MODEL}. Inject `fetchImpl` in tests.
 */
export function makeOpenAITransport({ env = process.env, model, apiKey, fetchImpl, log } = {}) {
  return makeChatTransport({
    baseUrl: OPENAI_BASE_URL,
    apiKey: apiKey ?? env.OPENAI_API_KEY,
    model: model ?? env.OPENAI_MODEL ?? DEFAULT_OPENAI_MODEL,
    fetchImpl,
    keyName: 'OPENAI_API_KEY',
    log,
  });
}

/**
 * The OpenAI registry entry.
 * @type {{ name:string, subAgentCapable:boolean, structuredOutput:string,
 *          runAgent:(opts?:object)=>Promise<any> }}
 */
export const openaiDriver = {
  name: 'openai',
  subAgentCapable: false,
  structuredOutput: 'json-mode (response_format json_schema)',
  async runAgent(opts = {}) {
    const { prompt, schema, label, log } = opts;
    const transport = makeOpenAITransport(opts);
    return runWithSchema({ transport, prompt, schema, label, log });
  },
};

export default openaiDriver;
