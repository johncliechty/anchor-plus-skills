import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { basename, extname, isAbsolute, relative, resolve } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { loadLedgerEntries } from "./index.mjs";

const LIMITATIONS = "Source meaning reviewed by recorded seats; deterministic binding does not itself infer meaning";

function requiredText(value, label) {
  assert.equal(typeof value, "string", label + " must be text");
  assert(value.trim(), label + " must not be empty");
  return value;
}

function absoluteFile(file, label) {
  requiredText(file, label);
  assert(isAbsolute(file), label + " must be absolute");
  return resolve(file);
}

function digestText(value, label) {
  assert.match(requiredText(value, label), /^[a-f0-9]{64}$/i, label + " must be SHA256");
  return value.toLowerCase();
}

function canonicalReceipt(value, label) {
  const receipt = value?.schema === "trio.seat.v1" ? value : value?.receipt;
  assert.equal(receipt?.schema, "trio.seat.v1", label + " must contain an actual seat receipt");
  return receipt;
}

function successfulReceipt(receipt, label, family) {
  assert.equal(receipt.ok, true, label + " must be successful");
  assert.equal(receipt.status, "success", label + " has inconsistent success status");
  requiredText(receipt.served?.family, label + " served family");
  assert.equal(receipt.served.family_attested, true, label + " family must be attested");
  if (family) assert.equal(receipt.served.family, family, label + " served family");
  if (receipt.served.model_attested === true) {
    requiredText(receipt.served.model, label + " attested model");
  }
}

function collectReceipts(value, output) {
  if (!value || typeof value !== "object") return;
  if (value.schema === "trio.seat.v1") output.push(value);
  for (const child of Object.values(value)) collectReceipts(child, output);
}

function indexEntries(entries, expected, label) {
  assert(Array.isArray(entries), label + " entries must be an array");
  const indexed = new Map();
  for (const entry of entries) {
    const id = requiredText(entry?.tuple?.id, label + " tuple ID");
    assert(!indexed.has(id), label + " duplicate ID: " + id);
    indexed.set(id, entry);
  }
  const missing = [...expected.keys()].filter(id => !indexed.has(id));
  const extra = [...indexed.keys()].filter(id => !expected.has(id));
  assert.equal(missing.length, 0, label + " missing IDs: " + missing.join(", "));
  assert.equal(extra.length, 0, label + " extra IDs: " + extra.join(", "));
  assert.equal(indexed.size, expected.size, label + " count mismatch");
  return indexed;
}

function assertNoAcceptance(tuple, label) {
  assert.equal(tuple.lock, "candidate", label + " must remain candidate");
  for (const object of [tuple, tuple.receipt]) {
    for (const key of ["accepted_by", "acceptance", "acceptance_receipt", "signed_acceptance"]) {
      assert.equal(object?.[key], undefined, label + " contains acceptance authority: " + key);
    }
    assert.notEqual(object?.author_acceptance, true, label + " claims author acceptance");
  }
}

function verifyShape(entry, expected, label) {
  const tuple = entry.tuple;
  assertNoAcceptance(tuple, label);
  assert.deepEqual(tuple.value, expected.value, label + " complete value mismatch");
  if (expected.kind !== undefined) assert.equal(tuple.kind, expected.kind, label + " kind mismatch");
  assert.equal(tuple.receipt?.span, expected.quote, label + " quote mismatch");
  assert.deepEqual(tuple.value?.context?.original_lines, expected.original_lines, label + " original lines mismatch");
}

/**
 * Verify a recorded product against its frozen evidence, never accept or edit it.
 * entries overrides only the recording-side entries. A hashed, dated public
 * capture preserves the real onboarding proof without freezing future writing.
 * verifyFiles:false omits hashes and original-file
 * passage checks, and reports that omission; intended evidence is still required.
 */
export function verifyProductEvidence(manifest, { entries, verifyFiles = true } = {}) {
  assert.equal(manifest?.schema, 1, "product evidence schema must be 1");
  const projectRoot = absoluteFile(manifest.project_root, "project_root");
  const recordingRoot = absoluteFile(manifest.recording_root, "recording_root");
  assert(Number.isInteger(manifest.expected_count) && manifest.expected_count > 0, "expected_count must be positive");
  for (const field of ["expected", "evidence", "semantic_checks", "reviews", "source_paths"]) {
    assert(Array.isArray(manifest[field]) && manifest[field].length > 0, field + " must not be empty");
  }
  assert.equal(typeof verifyFiles, "boolean", "verifyFiles must be boolean");

  const buffers = new Map();
  const hashes = new Map();
  const jsonFiles = new Map();
  function bytes(file) {
    const path = resolve(file);
    if (!buffers.has(path)) buffers.set(path, readFileSync(path));
    return buffers.get(path);
  }
  function json(file) {
    const path = resolve(file);
    if (!jsonFiles.has(path)) jsonFiles.set(path, JSON.parse(bytes(path).toString("utf8")));
    return jsonFiles.get(path);
  }
  function checkHash(file, expectedHash, label) {
    const path = absoluteFile(file, label + " file");
    const wanted = digestText(expectedHash, label + " SHA256");
    if (verifyFiles) {
      if (!hashes.has(path)) hashes.set(path, createHash("sha256").update(bytes(path)).digest("hex"));
      assert.equal(hashes.get(path), wanted, label + " hash mismatch: " + path);
    }
    return path;
  }

  const expected = new Map();
  const expectedFiles = new Set();
  for (const item of manifest.expected) {
    const file = checkHash(item.file, item.sha256, "expected");
    assert(!expectedFiles.has(file), "duplicate expected file: " + file);
    expectedFiles.add(file);
    const claims = json(file);
    assert(Array.isArray(claims), "expected claims must be an array: " + file);
    assert(Number.isInteger(item.count) && item.count >= 0, "expected file count must be an integer");
    assert.equal(claims.length, item.count, "expected file count mismatch: " + file);
    for (const claim of claims) {
      const id = requiredText(claim?.id, "expected claim ID");
      assert(!expected.has(id), "duplicate expected ID: " + id);
      requiredText(claim.quote, id + " expected quote");
      expected.set(id, claim);
    }
  }
  assert.equal(expected.size, manifest.expected_count, "total intended count mismatch");

  const evidenceFiles = new Map();
  const evidenceReceipts = [];
  for (const item of manifest.evidence) {
    const file = checkHash(item.file, item.sha256, "evidence");
    requiredText(item.role, "evidence role");
    if (evidenceFiles.has(file)) {
      assert.equal(evidenceFiles.get(file).sha256.toLowerCase(), item.sha256.toLowerCase(), "conflicting evidence hashes");
    }
    evidenceFiles.set(file, item);
    if (extname(file).toLowerCase() === ".json") collectReceipts(json(file), evidenceReceipts);
  }
  function requireEvidenceFile(file, label) {
    const path = absoluteFile(file, label);
    assert(evidenceFiles.has(path), label + " is not bound in evidence: " + path);
    return path;
  }
  function requireRecordedReceipt(receipt, label) {
    assert(evidenceReceipts.some(actual => isDeepStrictEqual(actual, receipt)), label + " is not preserved in the evidence receipts");
  }

  const reviewed = [];
  for (const item of manifest.reviews) {
    const file = requireEvidenceFile(item.file, "review file");
    const receiptFile = requireEvidenceFile(item.receipt_file, "review receipt file");
    const dispositionFile = requireEvidenceFile(item.disposition_file, "review disposition file");
    const review = json(file);
    assert(review && typeof review === "object" && Object.keys(review).length > 0, "review must contain actual recorded content");
    const verdict = requiredText(item.expected_verdict, "expected review verdict");
    if (item.verdict_path !== undefined) {
      assert(Array.isArray(item.verdict_path) && item.verdict_path.length > 0, "verdict_path must be a nonempty array");
      const actual = item.verdict_path.reduce((value, key) => value?.[key], review);
      assert.equal(requiredText(actual, "actual review verdict").trim().toLowerCase(), verdict.trim().toLowerCase(), "review verdict mismatch");
    } else {
      assert(JSON.stringify(review).toLowerCase().includes(JSON.stringify(verdict).toLowerCase()), "original review does not contain its expected verdict");
    }
    const receipt = canonicalReceipt(json(receiptFile), "review");
    successfulReceipt(receipt, "review", "grok");
    assert.equal(receipt.served.model_attested, true, "Grok review model must be attested");
    assert(Array.isArray(item.disposition_checks) && item.disposition_checks.length > 0, "review disposition checks must not be empty");
    const disposition = bytes(dispositionFile).toString("utf8");
    for (const check of item.disposition_checks) {
      assert(disposition.includes(requiredText(check, "disposition literal")), "review disposition is missing: " + check);
    }
    if (item.finding_dispositions) {
      const resolved = json(dispositionFile);
      const after = (resolved.changes || []).map(change => change.after).join('\n');
      for (const binding of item.finding_dispositions) {
        assert(review.findings?.some(finding => finding.id === binding.finding_id), 'unknown reviewed finding: ' + binding.finding_id);
        assert(Array.isArray(binding.after_includes) && binding.after_includes.length, 'missing disposition meaning');
        for (const text of binding.after_includes) assert(after.includes(text), 'missing applied disposition for ' + binding.finding_id);
      }
      for (const finding of review.findings || []) assert(item.finding_dispositions.some(binding => binding.finding_id === finding.id), 'undispositioned review finding: ' + finding.id);
    }
    reviewed.push({ file, verdict, disposition_file: dispositionFile, model_served: receipt.served.model });
  }

  const captured = manifest.public_capture ? json(checkHash(manifest.public_capture.file, manifest.public_capture.sha256, 'public capture')) : null;
  if (captured) assert.equal(captured.source_recording_root, recordingRoot, 'capture recording root differs');
  const recording = indexEntries(entries ?? captured?.recording_entries ?? loadLedgerEntries(recordingRoot), expected, "recording");
  let publicEntries;
  if (manifest.public_capture) {
    const capture = json(checkHash(manifest.public_capture.file, manifest.public_capture.sha256, 'public capture'));
    assert.equal(capture.source_project_root, projectRoot, 'public capture came from another project');
    assert(capture.captured_at && capture.live_verified === true, 'public capture lacks observed verification');
    assert.deepEqual(capture.config.ledger_sources, manifest.source_paths, 'captured source selection differs');
    publicEntries = capture.entries;
  } else publicEntries = loadLedgerEntries(projectRoot);
  const active = indexEntries(publicEntries, expected, "public selection");
  const originalFiles = new Set();
  const passageCache = new Map();
  let interrupted = 0;

  for (const [id, wanted] of expected) {
    const entry = recording.get(id);
    const selected = active.get(id);
    verifyShape(entry, wanted, id + " recording");
    verifyShape(selected, wanted, id + " public selection");
    assert.deepEqual(selected.tuple, entry.tuple, id + " selected tuple differs from recording");
    assert.equal(selected.prose, entry.prose, id + " selected prose differs from recording");
    const tuple = entry.tuple;
    const receipt = tuple.receipt;
    const context = tuple.value.context;
    const recorded = receipt.extraction?.recorded;
    assert(recorded && typeof recorded === "object", id + " missing recorded provenance");
    const original = recorded.original_source;
    assert(original && typeof original === "object", id + " missing original source");
    assert.equal(context.original_file, original.file, id + " original file mismatch");
    const originLines = context.original_lines;
    assert(Array.isArray(originLines) && originLines.length === 2 && originLines.every(Number.isInteger), id + " malformed original lines");
    assert(Number.isInteger(original.from) && Number.isInteger(original.to) && original.from >= 1 && original.to >= original.from, id + " malformed original source bounds");
    assert(Number.isInteger(receipt.line_hint) && receipt.line_hint >= 1, id + " malformed line hint");
    assert(originLines[1] >= originLines[0] && originLines[1] <= original.to, id + " original lines outside source");
    assert.equal(originLines[0], original.from + receipt.line_hint - 1, id + " original line arithmetic mismatch");
    const length = originLines[1] - originLines[0] + 1;
    requiredText(entry.prose, id + " source prose");
    const copiedLines = entry.prose.split("\n");
    assert(receipt.line_hint - 1 + length <= copiedLines.length, id + " quote extends past copied source");
    assert.equal(copiedLines.slice(receipt.line_hint - 1, receipt.line_hint - 1 + length).join("\n"), receipt.span, id + " exact copied-source span mismatch");

    const originalPath = resolve(projectRoot, requiredText(original.file, id + " original source path"));
    const withinProject = relative(projectRoot, originalPath);
    assert(!isAbsolute(withinProject) && withinProject !== ".." && !withinProject.startsWith(".." + "/") && !withinProject.startsWith(".." + "\\"), id + " original source escapes project");
    checkHash(originalPath, original.sha256, id + " original source");
    originalFiles.add(originalPath);
    let textPath = originalPath;
    if (original.derived !== undefined) {
      textPath = checkHash(resolve(projectRoot, requiredText(original.derived, id + " derived source path")), original.derived_sha256, id + " derived source");
      originalFiles.add(textPath);
    } else {
      assert.equal(original.derived_sha256, undefined, id + " derived hash without a derived source");
    }
    if (verifyFiles) {
      if (!passageCache.has(textPath)) passageCache.set(textPath, bytes(textPath).toString("utf8").replace(/\r\n/g, "\n").split("\n"));
      const lines = passageCache.get(textPath);
      assert(originLines[1] <= lines.length, id + " original passage extends past source");
      assert.equal(lines.slice(originLines[0] - 1, originLines[1]).join("\n"), receipt.span, id + " exact original-source passage mismatch");
    }

    const actualReceipt = canonicalReceipt(recorded.receipt, id + " author");
    requireRecordedReceipt(actualReceipt, id + " author receipt");
    assert(Array.isArray(recorded.raw_outputs) && recorded.raw_outputs.length > 0, id + " missing raw output bindings");
    for (const raw of recorded.raw_outputs) {
      const hash = digestText(raw.sha256, id + " raw output SHA256");
      const name = basename(requiredText(raw.file, id + " raw output file"));
      assert([...evidenceFiles].some(([file, item]) => basename(file) === name && item.sha256.toLowerCase() === hash), id + " raw output is not bound in evidence: " + name);
    }
    if (actualReceipt.ok === true) {
      successfulReceipt(actualReceipt, id + " author");
      assert.notEqual(context.origin_execution_status, "interrupted", id + " successful receipt mislabels interrupted origin");
    } else {
      assert.equal(actualReceipt.ok, false, id + " author receipt has no outcome");
      assert.equal(actualReceipt.error?.code?.toLowerCase(), "timeout", id + " failed origin must preserve timeout");
      assert.equal(recorded.durable_partial?.unreviewed, true, id + " interrupted output must remain explicitly unreviewed");
      assert.equal(context.origin_execution_status, "interrupted", id + " interrupted origin was relabeled");
      const completion = canonicalReceipt(recorded.completion?.receipt, id + " completion");
      successfulReceipt(completion, id + " completion");
      requireRecordedReceipt(completion, id + " completion receipt");
      requiredText(recorded.completion?.scope, id + " completion scope");
      assert(reviewed.length > 0, id + " interrupted output lacks preserved review disposition");
      interrupted += 1;
    }
  }

  const semanticIDs = new Set();
  for (const check of manifest.semantic_checks) {
    const id = requiredText(check.id, "semantic check ID");
    assert(!semanticIDs.has(id), "duplicate semantic check ID: " + id);
    semanticIDs.add(id);
    const entry = recording.get(id);
    assert(entry, "semantic check references missing entry: " + id);
    for (const field of ["object_includes", "quote_includes", "related_ids"]) {
      assert(Array.isArray(check[field]), id + " semantic " + field + " must be an array");
    }
    assert(check.object_includes.length + check.quote_includes.length + check.related_ids.length > 0, id + " semantic check has no requirements");
    const objectText = typeof entry.tuple.value.object === "string" ? entry.tuple.value.object : JSON.stringify(entry.tuple.value.object);
    for (const text of check.object_includes) assert(objectText.includes(requiredText(text, id + " object requirement")), id + " missing reviewed object text: " + text);
    for (const text of check.quote_includes) assert(entry.tuple.receipt.span.includes(requiredText(text, id + " quote requirement")), id + " missing reviewed quote text: " + text);
    const related = entry.tuple.value.context.narrative_links;
    for (const relatedID of check.related_ids) {
      requiredText(relatedID, id + " related ID");
      assert(Array.isArray(related) && related.includes(relatedID), id + " missing reviewed relationship: " + relatedID);
      assert(recording.has(relatedID), id + " relationship target is absent: " + relatedID);
    }
  }

  return {
    schema: 1,
    expected_count: expected.size,
    recording_count: recording.size,
    public_count: active.size,
    bindings_verified: expected.size,
    original_passages_verified: verifyFiles ? expected.size : 0,
    source_files_verified: verifyFiles ? originalFiles.size : 0,
    hashed_files_verified: hashes.size,
    files_verified: verifyFiles,
    semantic_checks_verified: semanticIDs.size,
    interrupted_origins_preserved: interrupted,
    reviews: reviewed,
    limitations: LIMITATIONS
  };
}
