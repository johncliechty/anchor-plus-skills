export const prismaExclusionsSchema = {
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PrismaExclusions",
  "type": "object",
  "required": ["exclusions"],
  "properties": {
    "exclusions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["paperId", "title", "reason"],
        "properties": {
          "paperId": { "type": "string" },
          "title": { "type": "string" },
          "reason": {
            "type": "string",
            "enum": ["low-venue", "low-tier", "date-range", "no-pdf", "duplicate", "off-topic", "fetch-failed", "no-text", "rank-truncated"]
          },
          "relevance_score": { "type": ["number", "null"], "minimum": 0, "maximum": 1 },
          "relevance_floor": { "type": "number", "minimum": 0, "maximum": 1 },
          "nearest_seed": { "type": ["string", "null"] },
          "details": { "type": "string" }
        }
      }
    }
  }
};
