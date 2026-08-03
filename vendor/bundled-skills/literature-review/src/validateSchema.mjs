import { assumptionsLedgerSchema } from './schemas/assumptionsLedger.mjs';
import { parameterizedMatrixSchema } from './schemas/parameterizedMatrix.mjs';
import { venueWhitelistSchema } from './schemas/venueWhitelist.mjs';
import { prismaExclusionsSchema } from './schemas/prismaExclusions.mjs';
import { telemetryEventSchema } from './schemas/telemetryEvent.mjs';
import { evidenceLedgerSchema } from './schemas/evidenceLedger.mjs';

export const schemas = {
  assumptionsLedger: assumptionsLedgerSchema,
  parameterizedMatrix: parameterizedMatrixSchema,
  venueWhitelist: venueWhitelistSchema,
  prismaExclusions: prismaExclusionsSchema,
  telemetryEvent: telemetryEventSchema,
  evidenceLedger: evidenceLedgerSchema
};

export class ValidationError extends Error {
  constructor(errors) {
    super(`Schema validation failed:\n${errors.map(e => `- ${e}`).join('\n')}`);
    this.name = 'ValidationError';
    this.errors = errors;
  }
}

export function validate(data, schema) {
  const errors = [];

  function check(val, sch, path = "") {
    if (!sch) return;

    // Check type
    if (sch.type) {
      const types = Array.isArray(sch.type) ? sch.type : [sch.type];
      let matched = false;
      for (const t of types) {
        if (t === "null" && val === null) matched = true;
        else if (t === "array" && Array.isArray(val)) matched = true;
        else if (t === "object" && val !== null && typeof val === "object" && !Array.isArray(val)) matched = true;
        else if (t === "integer" && Number.isInteger(val)) matched = true;
        else if (t === "number" && typeof val === "number") matched = true;
        else if (t === "string" && typeof val === "string") matched = true;
        else if (t === "boolean" && typeof val === "boolean") matched = true;
      }
      if (!matched) {
        errors.push(`${path || "value"} must be of type ${types.join(" or ")}, got ${val === null ? "null" : typeof val}`);
        return;
      }
    }

    // Check enum
    if (sch.enum) {
      if (!sch.enum.includes(val)) {
        errors.push(`${path || "value"} must be one of the allowed values: [${sch.enum.join(", ")}], got ${JSON.stringify(val)}`);
      }
    }

    // Check minimum / maximum
    if (typeof val === "number") {
      if (sch.minimum !== undefined && val < sch.minimum) {
        errors.push(`${path || "value"} must be >= ${sch.minimum}, got ${val}`);
      }
      if (sch.maximum !== undefined && val > sch.maximum) {
        errors.push(`${path || "value"} must be <= ${sch.maximum}, got ${val}`);
      }
    }

    // Check object properties
    if (val !== null && typeof val === "object" && !Array.isArray(val)) {
      if (sch.required) {
        for (const req of sch.required) {
          if (!(req in val)) {
            errors.push(`${path ? path + "." : ""}${req} is required`);
          }
        }
      }
      if (sch.properties) {
        // Check declared properties
        for (const k in sch.properties) {
          if (k in val) {
            check(val[k], sch.properties[k], path ? `${path}.${k}` : k);
          }
        }
      }
      // Check additional properties
      const props = sch.properties || {};
      for (const k in val) {
        if (!(k in props)) {
          if (sch.additionalProperties === false) {
            errors.push(`${path ? path + "." : ""}${k} is not allowed as an additional property`);
          } else if (sch.additionalProperties && typeof sch.additionalProperties === "object") {
            check(val[k], sch.additionalProperties, path ? `${path}.${k}` : k);
          }
        }
      }
    }

    // Check array items
    if (Array.isArray(val)) {
      if (sch.items) {
        val.forEach((item, idx) => {
          check(item, sch.items, `${path}[${idx}]`);
        });
      }
    }
  }

  check(data, schema);
  return {
    valid: errors.length === 0,
    errors
  };
}

export function validateSchema(payload, schemaOrName) {
  let schema = schemaOrName;
  if (typeof schemaOrName === 'string') {
    // Resolve by name (try exact, then lowercase matches)
    const key = Object.keys(schemas).find(
      k => k.toLowerCase() === schemaOrName.toLowerCase() ||
           schemas[k].title?.toLowerCase() === schemaOrName.toLowerCase()
    );
    if (!key) {
      throw new Error(`Unknown schema name: ${schemaOrName}`);
    }
    schema = schemas[key];
  }

  const result = validate(payload, schema);
  if (!result.valid) {
    throw new ValidationError(result.errors);
  }
  return true;
}
