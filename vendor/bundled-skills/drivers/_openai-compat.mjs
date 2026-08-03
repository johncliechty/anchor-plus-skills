// drivers/_openai-compat.mjs — request/response shaping shared by the OpenAI driver
// and the Grok (xAI) driver, whose Chat Completions API is OpenAI-compatible (same
// `/chat/completions` shape, `Bearer` auth, and `response_format` structured-output
// knob — only the base URL and model differ). The shaping functions are pure (no
// network), so request construction and reply parsing are unit-testable in isolation
// and the same code backs both backends.

import { HaltError } from '../foreman/bin/foreman-lib.mjs';

/**
 * Build the `{ url, init }` for an OpenAI-compatible Chat Completions request. When
 * `schema` is supplied, native structured output (JSON mode) is requested via
 * `response_format: { type:'json_schema', ... }` so the reply is constrained to the
 * schema; the shared seam still parses/validates and retries-then-abstains.
 */
export function buildChatRequest({ prompt, schema, model, apiKey, baseUrl }) {
  const body = {
    model,
    messages: [{ role: 'user', content: prompt }],
  };
  if (schema) {
    body.response_format = {
      type: 'json_schema',
      json_schema: { name: 'trio_response', schema, strict: false },
    };
  }
  return {
    url: `${baseUrl}/chat/completions`,
    init: {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        authorization: `Bearer ${apiKey ?? ''}`,
      },
      body: JSON.stringify(body),
    },
  };
}

/** Pull the assistant text out of a Chat Completions response (empty on miss). */
export function parseChatResponse(data) {
  return data?.choices?.[0]?.message?.content ?? '';
}

async function safeText(res) {
  try { return await res.text(); } catch { return ''; }
}

/**
 * Build a `transport(prompt, schema, label) => {text}` over an OpenAI-compatible
 * endpoint. Key gate: when no `apiKey` AND no injected `fetchImpl` are present, the
 * live path is unconfigured, so we HALT loudly rather than fire a keyless request —
 * tests skip the live smoke instead (they inject `fetchImpl`). A non-2xx reply also
 * HALTs with the status + a truncated body.
 * @param {object}   o
 * @param {string}   o.baseUrl
 * @param {?string}  [o.apiKey]
 * @param {string}   o.model
 * @param {?Function}[o.fetchImpl]  injected transport (tests); defaults to global fetch
 * @param {string}   [o.keyName]    env var name, for the "not set" HALT message
 * @param {Function} [o.log]
 */
export function makeChatTransport({ baseUrl, apiKey, model, fetchImpl, keyName = 'API key', log = () => {} } = {}) {
  if (!apiKey && !fetchImpl) {
    throw new HaltError(
      `${keyName} is not set`,
      `set ${keyName} in your environment to use this driver, or inject a fetchImpl/transport (tests/orchestrator)`,
    );
  }
  const doFetch = fetchImpl ?? globalThis.fetch;
  return async (prompt, schema, label = 'chat') => {
    const { url, init } = buildChatRequest({ prompt, schema, model, apiKey, baseUrl });
    const res = await doFetch(url, init);
    if (!res.ok) {
      const detail = await safeText(res);
      log(`   !! ${label}: HTTP ${res.status} from ${baseUrl}`);
      throw new HaltError(`chat request failed (HTTP ${res.status})`, String(detail).slice(0, 300));
    }
    const data = await res.json();
    return { text: parseChatResponse(data) };
  };
}
