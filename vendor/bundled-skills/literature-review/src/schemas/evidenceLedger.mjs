// Wave 4 — the rigid output schema for the joined inline Assumptions Ledger.
// This is the terminal-join contract: every accepted claim carries a complete
// evidence block (anchor hyperlink + verbatim/normalized quote + raw offsets)
// and machine-checkable provenance; every rejected claim and failed thread is
// a first-class, required part of the document — silent data loss is a schema
// violation, not a style choice. additionalProperties is false throughout so
// the join cannot smuggle undocumented fields past the validator.

export const evidenceLedgerSchema = {
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "EvidenceLedger",
  "type": "object",
  "required": ["stats", "sources", "accepted", "rejected", "failedThreads"],
  "additionalProperties": false,
  "properties": {
    "stats": {
      "type": "object",
      "required": [
        "threads", "completedThreads", "failedThreads",
        "claims", "accepted", "rejected", "duplicatesMerged"
      ],
      "additionalProperties": false,
      "properties": {
        "threads": { "type": "integer", "minimum": 0 },
        "completedThreads": { "type": "integer", "minimum": 0 },
        "failedThreads": { "type": "integer", "minimum": 0 },
        "claims": { "type": "integer", "minimum": 0 },
        "accepted": { "type": "integer", "minimum": 0 },
        "rejected": { "type": "integer", "minimum": 0 },
        "duplicatesMerged": { "type": "integer", "minimum": 0 }
      }
    },
    "sources": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["paperId", "title", "threadIds"],
        "additionalProperties": false,
        "properties": {
          "paperId": { "type": "string" },
          "title": { "type": ["string", "null"] },
          "threadIds": { "type": "array", "items": { "type": "integer" } }
        }
      }
    },
    "accepted": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claimId", "statement", "paperId", "column", "lineage", "evidence", "provenance"],
        "additionalProperties": false,
        "properties": {
          "claimId": { "type": "string" },
          "statement": { "type": "string" },
          "paperId": { "type": "string" },
          "column": { "type": ["string", "null"] },
          "lineage": { "type": "string", "enum": ["VERIFIED", "STRUCTURAL"] },
          "evidence": {
            "type": "object",
            "required": ["anchor", "verbatimQuote", "normalizedQuote", "start", "end", "occurrences"],
            "additionalProperties": false,
            "properties": {
              "anchor": { "type": "string" },
              "verbatimQuote": { "type": "string" },
              "normalizedQuote": { "type": "string" },
              "start": { "type": "integer", "minimum": 0 },
              "end": { "type": "integer", "minimum": 1 },
              "occurrences": { "type": "integer", "minimum": 1 }
            }
          },
          "provenance": {
            "type": "object",
            "required": ["batchIds", "workerIds"],
            "additionalProperties": false,
            "properties": {
              "batchIds": { "type": "array", "items": { "type": "integer" } },
              "workerIds": { "type": "array", "items": { "type": "string" } }
            }
          }
        }
      }
    },
    "rejected": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claimId", "statement", "paperId", "column", "quote", "reason", "rejection", "provenance"],
        "additionalProperties": false,
        "properties": {
          "claimId": { "type": "string" },
          "statement": { "type": "string" },
          "paperId": { "type": "string" },
          "column": { "type": ["string", "null"] },
          "quote": { "type": ["string", "null"] },
          "reason": { "type": "string" },
          "rejection": { "type": "string" },
          "provenance": {
            "type": "object",
            "required": ["batchIds", "workerIds"],
            "additionalProperties": false,
            "properties": {
              "batchIds": { "type": "array", "items": { "type": "integer" } },
              "workerIds": { "type": "array", "items": { "type": "string" } }
            }
          }
        }
      }
    },
    "failedThreads": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["batchId", "paperId", "workerId", "error"],
        "additionalProperties": false,
        "properties": {
          "batchId": { "type": "integer" },
          "paperId": { "type": "string" },
          "workerId": { "type": ["string", "null"] },
          "error": {
            "type": "object",
            "required": ["name", "message"],
            "additionalProperties": false,
            "properties": {
              "name": { "type": "string" },
              "message": { "type": "string" }
            }
          }
        }
      }
    }
  }
};
