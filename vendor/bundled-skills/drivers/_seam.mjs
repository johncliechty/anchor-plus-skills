// drivers/_seam.mjs — shared schema/retry/failure wrapper for the non-Claude API
// backends (gemini/openai/grok). The Claude backend keeps its own copy of this
// logic inline in claude.mjs (the Wave-4 byte-for-byte path, deliberately
// untouched); this module gives the API drivers the IDENTICAL contract so every
// backend behaves the same through `runAgent`:
//
//   - no schema           -> resolve to the model's text
//   - schema supplied     -> resolve to the parsed/validated object
//   - nonconforming JSON   -> retry exactly once (strict reprompt), then fail
//     without inventing a verdict or structured object.
//
// A `transport` is `(prompt, schema, label) => Promise<{ text }>`: it performs the
// actual request, baking native structured output into that request when `schema`
// is present (JSON-mode / function-calling), and returns the model's text. Tests
// inject a mock transport (or a mock `fetchImpl` into the driver) so the whole path
// runs with no network and no keys.

import { extractJson } from './claude.mjs';
import { runCliSchemaAttempts } from './cli-schema.mjs';

/**
 * Run a single agent turn through `transport`, applying the shared
 * schema/retry/failure contract.
 * @param {object}   o
 * @param {Function} o.transport  `(prompt, schema, label) => Promise<{text}>`
 * @param {string}   o.prompt
 * @param {object}   [o.schema]   JSON Schema; when present the reply is parsed/validated
 * @param {string}   [o.label]
 * @param {Function} [o.log]
 * @returns {Promise<any>} the model text or parsed schema-conforming object
 */
export async function runWithSchema({
  transport,
  prompt,
  schema,
  label = '(unlabeled)',
  log = () => {},
  driverOpts = {},
  familyName = 'API',
}) {
  return runCliSchemaAttempts({
    run: (physicalPrompt, physicalLabel) => transport(physicalPrompt, schema, physicalLabel),
    prompt,
    schema,
    label,
    driverOpts,
    familyName,
    log,
    parse: extractJson,
  });
}
