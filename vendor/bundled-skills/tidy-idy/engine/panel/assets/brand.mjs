// engine/panel/assets/brand.mjs — self-contained header brand (W2 / SC2 brand rows).
// Loads the in-skill SVG and exposes a data-URI for projection-only panel HTML.
// No file://, Anchor-absolute, or external URL.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DIR = path.dirname(fileURLToPath(import.meta.url));
export const BRAND_MARK_PATH = path.join(DIR, 'tidy-idy-mark.svg');

/**
 * Max expanded data-URI length for the header brand src attribute.
 * Numeric pin from polish mockup→assert matrix (SC2 brand criterion).
 */
export const HEADER_BRAND_DATA_URI_MAX_BYTES = 8192;

/** Raw SVG text of the shippable mark (trimmed). */
export function loadBrandSvg() {
  return fs.readFileSync(BRAND_MARK_PATH, 'utf8').trim();
}

/**
 * Compact self-contained data-URI for <img src>. Prefer percent-encoded svg+xml
 * (no base64 bloat) so CSP/size budgets stay measurable as plain string length.
 */
export function headerBrandDataUri() {
  const svg = loadBrandSvg();
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}
