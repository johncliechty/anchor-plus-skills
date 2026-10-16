export const assumptionsLedgerSchema = {
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "AssumptionsLedger",
  "type": "object",
  "required": ["assumptions"],
  "properties": {
    "assumptions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "statement", "type", "source"],
        "properties": {
          "id": { "type": "string" },
          "statement": { "type": "string" },
          "type": { "type": "string", "enum": ["OBSERVED", "CORROBORATED", "CLAIMED", "REFUTED"] },
          "source": {
            "type": "object",
            "required": ["title", "authors", "venue", "year"],
            "properties": {
              "title": { "type": "string" },
              "authors": { "type": "array", "items": { "type": "string" } },
              "venue": { "type": "string" },
              "year": { "type": "integer" },
              "citationCount": { "type": "integer" },
              "entityId": { "type": "string" }
            }
          },
          "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
          "context": { "type": "string" },
          "corroborationSources": { "type": "array", "items": { "type": "string" } },
          "conflicts": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["statement", "sourceId"],
              "properties": {
                "statement": { "type": "string" },
                "sourceId": { "type": "string" }
              }
            }
          }
        }
      }
    }
  }
};
