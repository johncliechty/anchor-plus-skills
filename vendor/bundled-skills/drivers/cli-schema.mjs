import {
  localAbortReceipt,
  rawTransportError,
  reportPhysicalReceipt,
} from './seat-contract.mjs';

const SUPPORTED_SCHEMA_KEYS = new Set([
  'type', 'properties', 'required', 'items', 'enum', 'nullable', 'pattern', 'minimum',
  // Annotation-only keys do not change conformance.
  '$schema', '$id', 'title', 'description',
]);
const JSON_TYPES = new Set([
  'object', 'array', 'string', 'number', 'integer', 'boolean', 'null',
]);

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function schemaShapeIsSupported(schema, seen = new WeakSet()) {
  if (typeof schema === 'boolean') return true;
  if (!isObject(schema) || seen.has(schema)) return false;
  seen.add(schema);
  if (Object.keys(schema).some((key) => !SUPPORTED_SCHEMA_KEYS.has(key))) return false;

  const types = Array.isArray(schema.type) ? schema.type : [schema.type];
  if (schema.type !== undefined
      && (types.length === 0 || types.some((type) => !JSON_TYPES.has(type)))) return false;
  if (schema.nullable !== undefined && typeof schema.nullable !== 'boolean') return false;
  if (schema.required !== undefined
      && (!Array.isArray(schema.required)
        || schema.required.some((key) => typeof key !== 'string')
        || new Set(schema.required).size !== schema.required.length)) return false;
  if (schema.enum !== undefined && (!Array.isArray(schema.enum) || schema.enum.length === 0)) {
    return false;
  }
  if (schema.pattern !== undefined) {
    if (typeof schema.pattern !== 'string') return false;
    try { new RegExp(schema.pattern); } catch { return false; }
  }
  if (schema.minimum !== undefined
      && (typeof schema.minimum !== 'number' || !Number.isFinite(schema.minimum))) return false;
  for (const key of ['$schema', '$id', 'title', 'description']) {
    if (schema[key] !== undefined && typeof schema[key] !== 'string') return false;
  }
  if (schema.properties !== undefined) {
    if (!isObject(schema.properties)) return false;
    for (const child of Object.values(schema.properties)) {
      if (!schemaShapeIsSupported(child, seen)) return false;
    }
  }
  if (schema.items !== undefined && !schemaShapeIsSupported(schema.items, seen)) return false;
  seen.delete(schema);
  return true;
}

function jsonEqual(left, right) {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right)
      && left.length === right.length
      && left.every((value, index) => jsonEqual(value, right[index]));
  }
  if (isObject(left) || isObject(right)) {
    if (!isObject(left) || !isObject(right)) return false;
    const leftKeys = Object.keys(left);
    const rightKeys = Object.keys(right);
    return leftKeys.length === rightKeys.length
      && leftKeys.every((key) => Object.hasOwn(right, key) && jsonEqual(left[key], right[key]));
  }
  return false;
}

function matchesType(value, type) {
  if (type === 'null') return value === null;
  if (type === 'array') return Array.isArray(value);
  if (type === 'object') return isObject(value);
  if (type === 'integer') return typeof value === 'number' && Number.isInteger(value);
  if (type === 'number') return typeof value === 'number' && Number.isFinite(value);
  return typeof value === type;
}

function valueConforms(value, schema) {
  if (schema === true) return true;
  if (schema === false) return false;
  if (value === null && schema.nullable === true) return true;
  if (schema.type !== undefined) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!types.some((type) => matchesType(value, type))) return false;
  }
  if (schema.enum !== undefined && !schema.enum.some((candidate) => jsonEqual(value, candidate))) {
    return false;
  }
  if (typeof value === 'string' && schema.pattern !== undefined
      && !new RegExp(schema.pattern).test(value)) return false;
  if (typeof value === 'number' && schema.minimum !== undefined && value < schema.minimum) {
    return false;
  }
  if (isObject(value)) {
    if (schema.required?.some((key) => !Object.hasOwn(value, key))) return false;
    for (const [key, child] of Object.entries(schema.properties ?? {})) {
      if (Object.hasOwn(value, key) && !valueConforms(value[key], child)) return false;
    }
  }
  if (Array.isArray(value) && schema.items !== undefined
      && value.some((item) => !valueConforms(item, schema.items))) return false;
  return true;
}

/** The deliberately small schema subset used by Trio; unknown semantics fail closed. */
export function conformsJsonSchema(value, schema) {
  return schemaShapeIsSupported(schema) && valueConforms(value, schema);
}

function schemaError(label) {
  const error = new Error(`provider reply remained schema-nonconforming after one reprompt (${label})`);
  error.seat_unavailable = true;
  error.seat_status = 'schema_nonconforming';
  return error;
}

/** Run at most two physical CLI calls while privately recording each outcome. */
export async function runCliSchemaAttempts({
  run,
  prompt,
  schema,
  label = '(unlabeled)',
  callOpts = {},
  driverOpts = {},
  familyName = 'model',
  log = () => {},
  conforms = conformsJsonSchema,
  parse,
} = {}) {
  if (typeof parse !== 'function') throw new TypeError('runCliSchemaAttempts requires parse()');
  const invoke = async (physicalPrompt, physicalLabel, kind) => {
    if (callOpts.signal?.aborted) {
      const rec = localAbortReceipt(physicalLabel, callOpts.model ?? null);
      reportPhysicalReceipt(driverOpts, { kind, label: physicalLabel, outcome: 'aborted', receipt: rec });
      throw rawTransportError(rec, familyName);
    }
    let result;
    try {
      result = await run(physicalPrompt, physicalLabel, callOpts);
    } catch (error) {
      const rec = error?.raw_receipt ?? null;
      reportPhysicalReceipt(driverOpts, {
        kind,
        label: physicalLabel,
        outcome: error?.aborted ? 'aborted' : 'seat_unavailable',
        receipt: rec,
        error: error?.message,
      });
      if (error?.aborted || error?.seat_unavailable) throw error;
      throw rawTransportError(rec, familyName);
    }
    const rec = result?.rec ?? null;
    if (!rec || rec.ok !== true) {
      reportPhysicalReceipt(driverOpts, {
        kind,
        label: physicalLabel,
        outcome: rec?.status === 'aborted' || rec?.aborted === true
          ? 'aborted'
          : 'seat_unavailable',
        receipt: rec,
      });
      throw rawTransportError(rec, familyName);
    }
    return { text: String(result?.text ?? ''), rec };
  };

  const schemaSuffix = schema
    ? `\n\nRespond with ONLY a single raw JSON object (no markdown fences, no prose) `
      + `that conforms to this JSON Schema:\n${JSON.stringify(schema)}`
    : '';
  const first = await invoke(prompt + schemaSuffix, label, 'initial');
  if (!schema) {
    reportPhysicalReceipt(driverOpts, {
      kind: 'initial', label, outcome: 'accepted', receipt: first.rec,
    });
    return first.text;
  }

  let parsed = parse(first.text);
  if (parsed && conforms(parsed, schema)) {
    reportPhysicalReceipt(driverOpts, {
      kind: 'initial', label, outcome: 'accepted', receipt: first.rec,
    });
    return parsed;
  }
  reportPhysicalReceipt(driverOpts, {
    kind: 'initial', label, outcome: 'schema_rejected', receipt: first.rec,
  });
  log(`   !! ${label} reply was schema-nonconforming — retrying once (strict reprompt)`);

  const strict = `${prompt}\n\nYour previous reply did not conform to the requested JSON Schema. `
    + `Respond with ONLY a single raw JSON object that conforms to this JSON Schema — `
    + `no prose, no markdown fences, nothing else:\n${JSON.stringify(schema)}`;
  const retryLabel = `${label}#retry`;
  const retry = await invoke(strict, retryLabel, 'schema_reprompt');
  parsed = parse(retry.text);
  if (parsed && conforms(parsed, schema)) {
    reportPhysicalReceipt(driverOpts, {
      kind: 'schema_reprompt', label: retryLabel, outcome: 'accepted', receipt: retry.rec,
    });
    return parsed;
  }
  reportPhysicalReceipt(driverOpts, {
    kind: 'schema_reprompt', label: retryLabel, outcome: 'schema_rejected', receipt: retry.rec,
  });
  throw schemaError(label);
}
