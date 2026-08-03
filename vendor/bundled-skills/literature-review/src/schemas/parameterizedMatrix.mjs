export const parameterizedMatrixSchema = {
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ParameterizedMatrix",
  "type": "object",
  "required": ["columns", "rows"],
  "properties": {
    "columns": {
      "type": "array",
      "items": { "type": "string" }
    },
    "rows": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["paperId", "title", "values"],
        "properties": {
          "paperId": { "type": "string" },
          "title": { "type": "string" },
          "values": {
            "type": "object",
            "additionalProperties": {
              "type": ["string", "number", "boolean", "null"]
            }
          }
        }
      }
    }
  }
};
