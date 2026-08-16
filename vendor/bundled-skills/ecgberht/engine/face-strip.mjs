/**
 * v0 Face+Strip storage: dual-section Face narrative + fenced/JSON Strip
 * and/or project-root strip.json. N=1 via cwd/--project; no registry.
 */

import fs from 'node:fs';
import path from 'node:path';

export const FACE_FILE_NAME = 'ECGBERHT.md';
export const STRIP_FILE_NAME = 'strip.json';
export const STRIP_SCHEMA_ID = 'ecgberht-strip-v0';

/** Face narrative field ids (human rewrite authority). */
export const FACE_NARRATIVE_FIELDS = Object.freeze([
  'north_star',
  'active_effort',
  'why_next',
  'human_wait',
  'why_stakes',
]);

/**
 * Resolve N=1 project path: --project wins, else cwd. Zero registry.
 * @param {{ project?: string|null, cwd?: string|null }} [opts]
 * @returns {string}
 */
export function resolveProjectPath(opts = {}) {
  const project = opts.project;
  if (typeof project === 'string' && project.trim()) {
    return path.resolve(project.trim());
  }
  const cwd = opts.cwd ?? process.cwd();
  return path.resolve(cwd);
}

/**
 * Extract first JSON fence that looks like an ecgberht Strip (schema id or strip-shaped).
 * Used for dual-section Face files; does not require loading full narrative for discovery.
 * @param {string} markdown
 * @returns {{ found: boolean, jsonText?: string, strip?: object, error?: string }}
 */
export function extractStripFence(markdown) {
  if (typeof markdown !== 'string' || !markdown) {
    return { found: false, error: 'empty_markdown' };
  }

  const fenceRe = /```(?:json)?\s*\r?\n([\s\S]*?)```/gi;
  let match;
  while ((match = fenceRe.exec(markdown)) !== null) {
    const jsonText = match[1].trim();
    if (!jsonText) continue;
    if (!jsonText.includes(STRIP_SCHEMA_ID) && !/"schema"\s*:/.test(jsonText)) {
      // Prefer fences that declare schema; still try parse if object-like
      if (!jsonText.startsWith('{')) continue;
    }
    try {
      const strip = JSON.parse(jsonText);
      if (strip && typeof strip === 'object' && !Array.isArray(strip)) {
        if (strip.schema === STRIP_SCHEMA_ID || typeof strip.phase === 'string') {
          return { found: true, jsonText, strip };
        }
      }
    } catch {
      // try next fence
    }
  }
  return { found: false, error: 'no_strip_fence' };
}

/**
 * True if text contains a discoverable Strip fence (cheap string check before full parse).
 * @param {string} markdown
 */
export function hasStripFenceMarker(markdown) {
  if (typeof markdown !== 'string') return false;
  return (
    markdown.includes(STRIP_SCHEMA_ID) ||
    /##\s*Strip\b/i.test(markdown)
  );
}

/**
 * Parse Face markdown into narrative sections by locked headings.
 * @param {string} markdown
 * @returns {{ ok: true, narrative: object, raw: string, strip_fence: object|null } | { ok: false, error: string }}
 */
export function parseFaceDocument(markdown) {
  if (typeof markdown !== 'string') {
    return { ok: false, error: 'face_not_string' };
  }

  const narrative = {
    north_star: sectionBody(markdown, 'North star'),
    active_effort: sectionBody(markdown, 'Active effort'),
    why_next: sectionBody(markdown, 'Why next'),
    human_wait: sectionBody(markdown, 'Human wait'),
    why_stakes: sectionBody(markdown, 'Why stakes') || sectionBody(markdown, 'Why next'),
  };

  const fence = extractStripFence(markdown);
  return {
    ok: true,
    narrative,
    raw: markdown,
    strip_fence: fence.found ? fence.strip : null,
  };
}

/**
 * @param {string} markdown
 * @param {string} heading
 */
function sectionBody(markdown, heading) {
  const re = new RegExp(
    `##\\s+${escapeRegExp(heading)}\\s*\\r?\\n([\\s\\S]*?)(?=\\r?\\n##\\s+|$)`,
    'i',
  );
  const m = markdown.match(re);
  return m ? m[1].trim() : '';
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Normalize / validate a Strip object (projection + optional append-only logs).
 * @param {object|string} input
 * @returns {{ ok: true, strip: object } | { ok: false, error: string, message?: string }}
 */
export function parseStrip(input) {
  let strip = input;
  if (typeof input === 'string') {
    try {
      strip = JSON.parse(input);
    } catch (e) {
      return { ok: false, error: 'strip_json_parse', message: String(e?.message ?? e) };
    }
  }
  if (!strip || typeof strip !== 'object' || Array.isArray(strip)) {
    return { ok: false, error: 'strip_not_object' };
  }

  const out = { ...strip };
  if (!out.schema) out.schema = STRIP_SCHEMA_ID;
  if (!Array.isArray(out.instruments)) out.instruments = Array.isArray(strip.instruments) ? [...strip.instruments] : [];
  if (!Array.isArray(out.receipts)) out.receipts = Array.isArray(strip.receipts) ? [...strip.receipts] : [];
  if (!Array.isArray(out.grasscatch)) out.grasscatch = Array.isArray(strip.grasscatch) ? [...strip.grasscatch] : [];
  if (!Array.isArray(out.uncertainty_flags)) {
    out.uncertainty_flags = Array.isArray(strip.uncertainty_flags) ? [...strip.uncertainty_flags] : [];
  }
  if (out.capacity !== 'known' && out.capacity !== 'unknown') {
    out.capacity = 'unknown';
  }
  if (typeof out.anti_starvation_age_days !== 'number') {
    out.anti_starvation_age_days =
      typeof strip.anti_starvation_age_days === 'number' ? strip.anti_starvation_age_days : 0;
  }
  if (!out.negative_heartbeat || typeof out.negative_heartbeat !== 'object') {
    out.negative_heartbeat = {
      no_attention_needed: false,
      why: null,
      until: null,
    };
  }

  return { ok: true, strip: out };
}

/**
 * Load project Face+Strip surfaces from disk (N=1 path).
 * Prefers strip.json; falls back to ECGBERHT.md fence. Never invents Strip truth.
 * @param {string} projectPath
 * @returns {object}
 */
export function loadProjectSurfaces(projectPath) {
  const root = path.resolve(projectPath);
  const stripPath = path.join(root, STRIP_FILE_NAME);
  const facePath = path.join(root, FACE_FILE_NAME);

  const result = {
    ok: true,
    project_path: root,
    face_path: null,
    strip_path: null,
    strip_source: null,
    face: null,
    strip: null,
    face_loaded: false,
    errors: [],
  };

  if (fs.existsSync(stripPath) && fs.statSync(stripPath).isFile()) {
    try {
      const raw = fs.readFileSync(stripPath, 'utf8');
      const parsed = parseStrip(raw);
      if (parsed.ok) {
        result.strip = parsed.strip;
        result.strip_path = stripPath;
        result.strip_source = 'strip.json';
      } else {
        result.errors.push(parsed);
      }
    } catch (e) {
      result.errors.push({ error: 'strip_read_failed', message: String(e?.message ?? e) });
    }
  }

  if (fs.existsSync(facePath) && fs.statSync(facePath).isFile()) {
    try {
      const raw = fs.readFileSync(facePath, 'utf8');
      const face = parseFaceDocument(raw);
      if (face.ok) {
        result.face = face;
        result.face_path = facePath;
        result.face_loaded = true;
        if (!result.strip && face.strip_fence) {
          const parsed = parseStrip(face.strip_fence);
          if (parsed.ok) {
            result.strip = parsed.strip;
            result.strip_source = 'face_fence';
          }
        }
      }
    } catch (e) {
      result.errors.push({ error: 'face_read_failed', message: String(e?.message ?? e) });
    }
  }

  if (!result.strip && !result.face) {
    result.ok = false;
    result.error = 'no_face_or_strip';
  }

  return result;
}

/**
 * Strip projection fields used for portfolio rank (no Face required).
 * @param {object} strip
 * @param {{ project_path?: string, strip_source?: string }} [meta]
 */
export function toStripProjection(strip, meta = {}) {
  const parsed = parseStrip(strip);
  if (!parsed.ok) {
    return null;
  }
  const s = parsed.strip;
  return {
    project_id: s.project_id ?? meta.project_id ?? null,
    project_path: meta.project_path ?? null,
    strip_source: meta.strip_source ?? null,
    phase: s.phase ?? null,
    active_effort: s.active_effort ?? null,
    human_wait: s.human_wait ?? 'none',
    capacity: s.capacity === 'known' ? 'known' : 'unknown',
    negative_heartbeat: s.negative_heartbeat ?? {
      no_attention_needed: false,
      why: null,
      until: null,
    },
    anti_starvation_age_days:
      typeof s.anti_starvation_age_days === 'number' ? s.anti_starvation_age_days : 0,
    next_recommended: s.next_recommended ?? null,
    why_next: s.why_next ?? null,
    uncertainty_flags: Array.isArray(s.uncertainty_flags) ? [...s.uncertainty_flags] : [],
    tool_depth_cell: s.tool_depth_cell ?? null,
    as_of: s.as_of ?? null,
  };
}
