// drivers/gemini.mjs — the Gemini (Google Generative Language API) model backend
// behind the trio `runAgent` seam.
//
// Gemini's REST shape differs from the OpenAI family (a `:generateContent` endpoint,
// an `x-goog-api-key` header, `contents[].parts[].text` payloads, and a
// `generationConfig.responseSchema` structured-output knob), so it has its own pure
// request/response shaping below rather than sharing the OpenAI-compatible builder.
//
// Capability profile: NOT sub-agent-capable (raw HTTP API); structured output is
// NATIVE — when a `schema` is supplied the request sets
// `responseMimeType:'application/json'` + `responseSchema`, and the shared seam
// parses/validates with retry-once-then-ABSTAIN so behavior matches every other
// backend. Selected via `TRIO_DRIVER=gemini`. The key lives in `GEMINI_API_KEY`;
// with no key and no injected transport the driver HALTs rather than firing a
// keyless request, so the live smoke test SKIPS when the key is absent — never fails.

import { HaltError } from '../foreman/bin/foreman-lib.mjs';
import { runWithSchema } from './_seam.mjs';

export const GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta';
// Rolling-latest alias: the prior pinned default (gemini-2.0-flash) was retired by the
// API ("no longer available", HTTP 404 on generateContent). `gemini-flash-latest` tracks
// the current GA flash model so this default cannot silently go stale again. Override per
// call or via GEMINI_MODEL for a pinned id.
export const DEFAULT_GEMINI_MODEL = 'gemini-flash-latest';

/**
 * Build the `{ url, init }` for a Gemini `generateContent` request. When `schema`
 * is supplied, native JSON output is requested via
 * `generationConfig.responseMimeType` + `responseSchema`.
 */
export function buildGeminiRequest({ prompt, schema, model, apiKey, baseUrl = GEMINI_BASE_URL }) {
  const body = { contents: [{ role: 'user', parts: [{ text: prompt }] }] };
  if (schema) {
    body.generationConfig = {
      responseMimeType: 'application/json',
      responseSchema: schema,
    };
  }
  return {
    url: `${baseUrl}/models/${model}:generateContent`,
    init: {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-goog-api-key': apiKey ?? '',
      },
      body: JSON.stringify(body),
    },
  };
}

/** Concatenate the text parts of a Gemini response (empty string on miss). */
export function parseGeminiResponse(data) {
  const parts = data?.candidates?.[0]?.content?.parts;
  if (!Array.isArray(parts)) return '';
  return parts.map((p) => p?.text ?? '').join('').trim();
}

async function safeText(res) {
  try { return await res.text(); } catch { return ''; }
}

/**
 * Build the Gemini transport. Reads the key/model from `opts` then env, defaulting
 * the model to {@link DEFAULT_GEMINI_MODEL}. With no key and no injected `fetchImpl`
 * the driver HALTs rather than firing a keyless request. Inject `fetchImpl` in tests.
 */
export function makeGeminiTransport({ env = process.env, model, apiKey, fetchImpl, log = () => {} } = {}) {
  const key = apiKey ?? env.GEMINI_API_KEY;
  if (!key && !fetchImpl) {
    throw new HaltError(
      'GEMINI_API_KEY is not set',
      'set GEMINI_API_KEY in your environment to use this driver, or inject a fetchImpl/transport (tests/orchestrator)',
    );
  }
  const mdl = model ?? env.GEMINI_MODEL ?? DEFAULT_GEMINI_MODEL;
  const doFetch = fetchImpl ?? globalThis.fetch;
  return async (prompt, schema, label = 'gemini') => {
    const { url, init } = buildGeminiRequest({ prompt, schema, model: mdl, apiKey: key });
    const res = await doFetch(url, init);
    if (!res.ok) {
      const detail = await safeText(res);
      log(`   !! ${label}: HTTP ${res.status} from ${GEMINI_BASE_URL}`);
      throw new HaltError(`gemini request failed (HTTP ${res.status})`, String(detail).slice(0, 300));
    }
    const data = await res.json();
    return { text: parseGeminiResponse(data) };
  };
}

/**
 * The Gemini registry entry.
 * @type {{ name:string, subAgentCapable:boolean, structuredOutput:string,
 *          runAgent:(opts?:object)=>Promise<any> }}
 */
export const geminiDriver = {
  name: 'gemini',
  subAgentCapable: false,
  structuredOutput: 'json-mode (responseSchema)',
  async runAgent(opts = {}) {
    const { prompt, schema, label, log } = opts;
    const transport = makeGeminiTransport(opts);
    return runWithSchema({ transport, prompt, schema, label, log });
  },
};

export default geminiDriver;
