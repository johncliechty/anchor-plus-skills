/**
 * Deterministic loaders for skill pack schemas and fixtures (W1).
 * Paths are relative to skill root — no host-absolute strings.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ENGINE_DIR = path.dirname(fileURLToPath(import.meta.url));

/** Skill pack root (parent of engine/). */
export function skillRoot() {
  return path.resolve(ENGINE_DIR, '..');
}

/**
 * Read and parse JSON under the skill root.
 * @param {...string} parts relative path segments
 */
export function loadJsonRelative(...parts) {
  const filePath = path.join(skillRoot(), ...parts);
  const raw = fs.readFileSync(filePath, 'utf8');
  return JSON.parse(raw);
}

/** Read UTF-8 text under the skill root. */
export function loadTextRelative(...parts) {
  const filePath = path.join(skillRoot(), ...parts);
  return fs.readFileSync(filePath, 'utf8');
}

export function loadStripSchema() {
  return loadJsonRelative('schema', 'strip.schema.json');
}

export function loadReceiptSchema() {
  return loadJsonRelative('schema', 'receipt.schema.json');
}

/** Wave 4 — skill-owned durable handback-file contract schema. */
export function loadHandbackContractSchema() {
  return loadJsonRelative('schema', 'handback-contract.schema.json');
}

export function loadFaceMarkers() {
  return loadJsonRelative('schema', 'face-markers.json');
}

export function loadDispatchTableSeed() {
  return loadJsonRelative('fixtures', 'dispatch-table-seed.json');
}

export function loadStripFixture() {
  return loadJsonRelative('fixtures', 'strip-minimal.json');
}

export function loadRoadmapSchema() {
  return loadJsonRelative('schema', 'roadmap.schema.json');
}

export function loadRoadmapTemplate() {
  return loadJsonRelative('templates', 'roadmap.json');
}

export function loadRoadmapFixture() {
  return loadJsonRelative('fixtures', 'roadmap-minimal.json');
}

export function loadE7StubTemplate() {
  return loadJsonRelative('templates', 'roadmap-e7-stubs.json');
}

export function loadGrasscatcherLedgerFixture() {
  return loadJsonRelative('fixtures', 'grasscatcher-ledger.json');
}

export function loadStage2FreezeFixture() {
  return loadJsonRelative('fixtures', 'stage2-freeze.json');
}

export function loadFaceTemplate() {
  return loadTextRelative('templates', 'ECGBERHT.md');
}

export function loadStripTemplate() {
  return loadJsonRelative('templates', 'strip.json');
}

/**
 * Load core pack surfaces used by the CLI stub / later verbs.
 * @returns {{ stripSchema: object, receiptSchema: object, faceMarkers: object, dispatchSeed: object, stripFixture: object, grasscatcherLedger: object, stage2Freeze: object }}
 */
export function loadPackSurfaces() {
  return {
    stripSchema: loadStripSchema(),
    receiptSchema: loadReceiptSchema(),
    faceMarkers: loadFaceMarkers(),
    dispatchSeed: loadDispatchTableSeed(),
    stripFixture: loadStripFixture(),
    grasscatcherLedger: loadGrasscatcherLedgerFixture(),
    stage2Freeze: loadStage2FreezeFixture(),
    roadmapSchema: loadRoadmapSchema(),
    roadmapFixture: loadRoadmapFixture(),
  };
}
