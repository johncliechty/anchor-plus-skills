// drivers/_seam.mjs — shared schema/retry/abstain wrapper for the non-Claude API
// backends (gemini/openai/grok). The Claude backend keeps its own copy of this
// logic inline in claude.mjs (the Wave-4 byte-for-byte path, deliberately
// untouched); this module gives the API drivers the IDENTICAL contract so every
// backend behaves the same through `runAgent`:
//
//   - no schema           -> resolve to the model's text
//   - schema supplied     -> resolve to the parsed/validated object
//   - unparseable JSON     -> retry exactly once (strict reprompt), then ABSTAIN
//     with `{ answerable:'no', findings:[] }` so the engine HALTs for a human
//     rather than acting on garbage (same shape Claude emits).
//
// A `transport` is `(prompt, schema, label) => Promise<{ text }>`: it performs the
// actual request, baking native structured output into that request when `schema`
// is present (JSON-mode / function-calling), and returns the model's text. Tests
// inject a mock transport (or a mock `fetchImpl` into the driver) so the whole path
// runs with no network and no keys.

import { extractJson } from './claude.mjs';

/**
 * Run a single agent turn through `transport`, applying the shared
 * schema/retry/abstain contract.
 * @param {object}   o
 * @param {Function} o.transport  `(prompt, schema, label) => Promise<{text}>`
 * @param {string}   o.prompt
 * @param {object}   [o.schema]   JSON Schema; when present the reply is parsed/validated
 * @param {string}   [o.label]
 * @param {Function} [o.log]
 * @returns {Promise<any>} the model text, or the parsed object (or the ABSTAIN object)
 */
export async function runWithSchema({ transport, prompt, schema, label = '(unlabeled)', log = () => {} }) {
  const { text } = await transport(prompt, schema, label);
  if (!schema) return text;

  let obj = extractJson(text);
  if (!obj) {
    log(`   !! ${label} reply was not valid JSON — retrying once (strict reprompt)`);
    const strict = `${prompt}\n\nYour previous reply was NOT valid JSON and could not be parsed. ` +
      `Respond with ONLY a single raw JSON object that conforms to the requested schema — ` +
      `no prose, no markdown fences, nothing else.`;
    obj = extractJson((await transport(strict, schema, `${label}#retry`)).text);
  }
  if (!obj) {
    log(`   !! ${label} still unparseable after retry — TRANSPORT FAILURE (abstain; degradable)`);
    return {
      answerable: 'no',
      transport_failed: true,
      note: `reviewer ${label} response was not parseable JSON after one retry ` +
        `(transport failure, not a plan problem)`,
      findings: [],
    };
  }
  return obj;
}
