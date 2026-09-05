export const prismaInclusionsSchema = {
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PrismaInclusions",
  "type": "object",
  "required": ["inclusions"],
  "properties": {
    "inclusions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["paperId", "title", "reason", "relevance_exempt"],
        "properties": {
          "paperId": { "type": "string" },
          "title": { "type": "string" },
          "reason": {
            "type": "string",
            "enum": ["user-seed"]
          },
          "relevance_exempt": { "type": "boolean" },
          "seed_identity": { "type": ["string", "null"] },
          "details": { "type": "string" }
        }
      }
    }
  }
};
