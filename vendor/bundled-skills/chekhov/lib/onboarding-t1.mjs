import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { scenesOf } from "./commit.mjs";

const ROLES = new Set(["current-manuscript", "current-plan", "additional-writing", "bible", "history", "unspecified"]);
const clone = value => structuredClone(value);
const fingerprint = value => createHash("sha256").update(JSON.stringify(value), "utf8").digest("hex");

function pick(object, keys) {
  const result = {};
  for (const key of keys) if (object?.[key] !== undefined) result[key] = clone(object[key]);
  return result;
}

function actualSourceFile(entry) {
  return entry.verdict_id ? "chekhov/VERDICTS.md" : String(entry.sidecar ?? "").replace(/\.ledger\.ya?ml$/i, "");
}

function displayPath(file) {
  return typeof file === "string" ? file.replace(/\\/g, "/").replace(/^(?:\.\/)+/, "") : "";
}

/** Bind only an exact, continuous span contained in one existing parser scene. */
export function bindRecordedSpan(text, receipt) {
  if (typeof text !== "string" || typeof receipt?.span !== "string" || !receipt.span) return null;
  const headingPath = receipt.heading_path ?? [];
  if (!Array.isArray(headingPath)) return null;
  const scenes = scenesOf({ file: "source.md", text });
  const lineStarts = [0];
  for (let offset = text.indexOf("\n"); offset !== -1; offset = text.indexOf("\n", offset + 1)) lineStarts.push(offset + 1);
  const candidates = [];
  for (let offset = text.indexOf(receipt.span); offset !== -1; offset = text.indexOf(receipt.span, offset + 1)) {
    const sceneIndex = scenes.findIndex((scene, index) => {
      const start = lineStarts[scene.line - 1];
      const end = index + 1 < scenes.length ? lineStarts[scenes[index + 1].line - 1] : text.length;
      return start !== undefined && offset >= start && offset + receipt.span.length <= end;
    });
    if (sceneIndex === -1) continue;
    const scene = scenes[sceneIndex];
    if (headingPath.length && !isDeepStrictEqual(headingPath, scene.heading_path)) continue;
    const line = text.slice(0, offset).split("\n").length;
    candidates.push({ offset, line, heading_path: clone(scene.heading_path) });
  }
  if (candidates.length === 1) return candidates[0];
  if (!Number.isInteger(receipt.line_hint)) return null;
  const hinted = candidates.filter(candidate => candidate.line === receipt.line_hint);
  return hinted.length === 1 ? hinted[0] : null;
}

function mappedRole(value) {
  if (typeof value !== "string") return "unspecified";
  const exact = value.trim().toLowerCase();
  if (ROLES.has(exact)) return exact;
  // A comparison names another source, not this source's role. Keep the full
  // declaration in provenance while classifying its primary descriptor.
  const text = exact.replace(/_/g, " ").split(/[;\r\n]|\b(?:compared (?:with|to)|versus|in contrast to|rather than)\b/, 1)[0].trim();
  if (/\b(older|legacy|historical|history|superseded|archived|earlier draft)\b/.test(text)) return "history";
  if (/\bbible\b/.test(text)) return "bible";
  if (/\bcurrent[\s-]+manuscript\b/.test(text) && !/\bnot (?:the )?current[\s-]+manuscript\b/.test(text)) return "current-manuscript";
  if (/\badditional[\s-]+(?:writing|prose|material)\b/.test(text)) return "additional-writing";
  if (/\b(plan|planned|planning|outline|proposed|proposal|future|adaptation|author intent|unwritten)\b/.test(text)) return "current-plan";
  if (/\b(manuscript|written (?:prose|scene|chapter|novella|story|book))\b/.test(text) && !/\bnot (?:yet )?written\b/.test(text)) return "current-manuscript";
  return "unspecified";
}

function strings(value) {
  return Array.isArray(value) ? value.filter(item => typeof item === "string" && item) : typeof value === "string" && value ? [value] : [];
}

/** Preserve source qualification separately from the history of its capture. */
export function sourceDescription(entry, selected = []) {
  const tuple = entry.tuple ?? {};
  const receipt = tuple.receipt ?? {};
  const declared = tuple.source && typeof tuple.source === "object" ? tuple.source : {};
  const context = tuple.value?.context ?? {};
  const file = actualSourceFile(entry);
  const selection = Array.isArray(selected) ? selected.find(item =>
    displayPath(item.file) === displayPath(file) &&
    typeof item.span === "string" &&
    typeof receipt.span === "string" &&
    item.span.includes(receipt.span)
  ) : undefined;
  let role = "unspecified";
  if (selection && ROLES.has(selection.role)) role = selection.role;
  else {
    for (const candidate of [declared.role, context.source_role, receipt.source_role, declared.attribution, context.attribution, receipt.attribution]) {
      const mapped = mappedRole(candidate);
      if (mapped !== "unspecified") { role = mapped; break; }
    }
  }
  const limitations = [
    ...strings(selection?.limitations),
    ...strings(declared.limitations),
    ...strings(declared.attribution),
    ...strings(receipt.attribution)
  ];
  if (role === "history") limitations.push("history");
  if (role === "current-plan") limitations.push("planned-adaptation");
  if (entry.verdict_id) limitations.push("idea-candidate");
  if (typeof declared.status === "string" && !["accepted", "canonical", "current", "written", "final"].includes(declared.status.toLowerCase())) limitations.push(declared.status);
  if (typeof tuple.source === "string") limitations.push(tuple.source);
  if (typeof context.attribution === "string" && /\b(character[\s_-]*(?:claim|statement)|dialogue|belief|rumou?r|hearsay|recollection|unreliable|hypothesis)\b/i.test(context.attribution)) limitations.push(context.attribution);
  if (typeof context.note === "string" && /\b(proposed|proposal|hypothetical|uncertain|unresolved|unproven|conditional|contradiction|contradictory|not (?:yet )?(?:integrated|established|proved|proven))\b/i.test(context.note)) limitations.push(context.note);
  const provenance = {
    ...pick(context, ["source_role", "attribution", "origin_execution_status", "note", "original_file", "original_lines"]),
    recorded_source_file: receipt.source_file ?? null,
    actual_source_file: file
  };
  if (receipt.source_role !== undefined) provenance.receipt_source_role = clone(receipt.source_role);
  if (receipt.attribution !== undefined) provenance.receipt_attribution = clone(receipt.attribution);
  if (declared.status !== undefined) provenance.declared_status = clone(declared.status);
  if (selection) provenance.selected_role = selection.role;
  return { file, role, limitations: [...new Set(limitations)], original: clone(tuple.source ?? null), provenance };
}

function relativePath(value, { prefix = false } = {}) {
  if (typeof value !== "string" || !value || value.includes("\0") || value.includes(":")) return null;
  let normalized = value.replace(/\\/g, "/");
  if (normalized.startsWith("/") || (prefix && !normalized.endsWith("/"))) return null;
  normalized = normalized.replace(/^(?:\.\/)+/, "");
  if (prefix) normalized = normalized.slice(0, -1);
  const parts = normalized.split("/");
  if (!parts.length || parts.some(part => !part || part === "." || part === "..")) return null;
  return parts.join("/") + (prefix ? "/" : "");
}

function inside(root, target) {
  const difference = path.relative(root, target);
  return difference === "" || (!path.isAbsolute(difference) && difference !== ".." && !difference.startsWith(".." + path.sep));
}

/** A relocation is accepted only when declared and contained in selected roots. */
export function sourceReferenceMatches(root, recordedFile, actualFile) {
  const recorded = relativePath(recordedFile);
  const actual = relativePath(actualFile);
  if (!recorded || !actual) return false;
  if (recorded === actual) return true;
  try {
    const config = JSON.parse(fs.readFileSync(path.join(root, "chekhov", "config.json"), "utf8"));
    if (!Array.isArray(config.source_relocations) || !Array.isArray(config.ledger_sources)) return false;
    const selections = config.ledger_sources.map(value => relativePath(typeof value === "string" ? value.replace(/[\\/]$/, "") : value)).filter(Boolean);
    const projectReal = fs.realpathSync(root);
    for (const mapping of config.source_relocations) {
      const from = relativePath(mapping?.from, { prefix: true });
      const to = relativePath(mapping?.to, { prefix: true });
      if (!from || !to || !recorded.startsWith(from) || to + recorded.slice(from.length) !== actual) continue;
      const destination = to.slice(0, -1);
      for (const selection of selections) {
        if (destination !== selection && !destination.startsWith(selection + "/")) continue;
        const selectedReal = fs.realpathSync(path.resolve(root, selection));
        const actualReal = fs.realpathSync(path.resolve(root, actual));
        if (!inside(projectReal, selectedReal) || !inside(selectedReal, actualReal)) continue;
        if (!fs.statSync(actualReal).isFile()) continue;
        return true;
      }
    }
    return false;
  } catch {
    return false;
  }
}

function seatSummary(receipt) {
  if (!receipt || typeof receipt !== "object") return undefined;
  const result = pick(receipt, ["schema", "ok", "status"]);
  if (receipt.served) result.served = pick(receipt.served, ["driver", "family", "model", "family_attested", "model_attested"]);
  if (receipt.error?.code !== undefined) result.error_code = clone(receipt.error.code);
  return result;
}

/** Compact repeated transport audit data without truncating story evidence. */
export function compactLedgerRow(row) {
  const result = clone(row);
  const receipt = row.receipt;
  if (!receipt || typeof receipt !== "object") return result;
  result.receipt = pick(receipt, ["span", "heading_path", "line_hint", "date", "source_file"]);
  for (const key of ["verdict_id", "line_hash"]) if (typeof receipt[key] === "string") result.receipt[key] = receipt[key];
  const extraction = receipt.extraction ?? {};
  const recorded = extraction.recorded ?? {};
  const audit = {
    ...(result.receipt_provenance && typeof result.receipt_provenance === "object" ? result.receipt_provenance : {}),
    receipt_json_sha256: fingerprint(receipt),
    recorded_source_file: receipt.source_file ?? null,
    ...pick(row.value?.context, ["origin_execution_status"])
  };
  if (typeof row.source?.file === "string") audit.actual_source_file = row.source.file;
  else if (typeof row.sidecar === "string") audit.actual_source_file = actualSourceFile(row);
  const extractionSummary = pick(extraction, ["mode", "served_model", "model_attested", "tool_isolation_verified", "runtime_policy_status"]);
  if (Object.keys(extractionSummary).length) audit.extraction = extractionSummary;
  if (recorded.receipt) {
    audit.author_receipt_json_sha256 = fingerprint(recorded.receipt);
    audit.author = seatSummary(recorded.receipt);
  }
  if (recorded.original_source) audit.original_source = pick(recorded.original_source, ["file", "sha256", "from", "to", "role", "derived", "derived_sha256"]);
  if (recorded.durable_partial) audit.durable_partial = pick(recorded.durable_partial, ["unreviewed", "failed_at", "scope"]);
  if (recorded.completion) {
    audit.completion = pick(recorded.completion, ["scope", "receipt_file", "prompt_hash"]);
    if (recorded.completion.receipt) audit.completion.receipt = seatSummary(recorded.completion.receipt);
  }
  if (recorded.operator_corrections) audit.operator_corrections = pick(recorded.operator_corrections, ["file", "sha256", "affected_records", "author_acceptance"]);
  if (Array.isArray(recorded.raw_outputs)) audit.raw_output_count = recorded.raw_outputs.length;
  result.receipt_provenance = audit;
  return result;
}
