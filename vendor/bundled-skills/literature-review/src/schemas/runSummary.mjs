export const runSummarySchema = {
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "RunSummary",
  "type": "object",
  "required": [
    "version",
    "relevance_floor",
    "corpus_relevance_min",
    "extracted",
    "extracted_at_or_above_floor",
    "corpus_relevance",
    "floor_active",
    "verdict",
    "ledger_status"
  ],
  "properties": {
    "version": { "type": "string" },
    "relevance_floor": { "type": "number", "minimum": 0, "maximum": 1 },
    "corpus_relevance_min": { "type": "number", "minimum": 0, "maximum": 1 },
    "extracted": { "type": "integer", "minimum": 0 },
    "extracted_at_or_above_floor": { "type": "integer", "minimum": 0 },
    "corpus_relevance": { "type": ["number", "null"], "minimum": 0, "maximum": 1 },
    "floor_active": { "type": "boolean" },
    "verdict": { "type": ["string", "null"] },
    "ledger_status": { "type": "string", "enum": ["partial", "complete", "none"] }
  }
};
