/**
 * lib/inventory.mjs — the Artificial Magi inventory (W2).
 *
 * Artificial Magi's existing markdown is ALREADY CANONICAL IN FORM: it is
 * listed here with status "inventoried" — the flip to "canonical" happens
 * only through W13's first job (the Spine v4 consistency pass), never here.
 * The artificial-magi root is READ-ONLY to this wave; paths are relative to
 * that root (roots.json fixes the absolute path).
 */
import fs from 'node:fs';
import path from 'node:path';
import { sha256Bytes } from './migrate.mjs';

export const INVENTORY_STATUS = 'inventoried';

export const AM_INVENTORY = Object.freeze([
  Object.freeze({
    id: 'am.bible-full-text',
    role: 'the full-text bible md',
    rel: 'Session_Notes/bible_v0.6_full_text.md',
    status: INVENTORY_STATUS,
  }),
  Object.freeze({
    id: 'am.spine-v4',
    role: 'Spine v4',
    rel: 'Book 1/Book 1 Ghost in the Code/Current/Ghost_in_the_Code_Spine_v4.md',
    status: INVENTORY_STATUS,
  }),
  Object.freeze({
    id: 'am.chapter-outline-v2',
    role: 'Chapter Outline v2',
    rel: 'Book 1/Book 1 Ghost in the Code/Current/Ghost_in_the_Code_Chapter_Outline_v2.md',
    status: INVENTORY_STATUS,
  }),
  Object.freeze({
    id: 'am.beat-sheet',
    role: 'Beat Sheet md',
    rel: 'Book 1/Book 1 Ghost in the Code/Current/Ghost_in_the_Code_BeatSheet_Ch1-3_v1.md',
    status: INVENTORY_STATUS,
  }),
  Object.freeze({
    id: 'am.appendix-a-four-part-pacing',
    role: 'Appendix A Four-Part Pacing CANONICAL v0.6',
    rel: 'Series Bible/Appendix_A_Four_Part_Pacing_CANONICAL_v0.6.md',
    status: INVENTORY_STATUS,
  }),
]);

/**
 * Resolve the inventory against the real root: existence + SHA-256 recorded,
 * status untouched (W13's first job is the only flipper). Reads only.
 */
export function amInventory(rootPath) {
  return AM_INVENTORY.map((entry) => {
    const abs = path.join(rootPath, entry.rel);
    const exists = fs.existsSync(abs);
    return {
      ...entry,
      exists,
      sha256: exists ? sha256Bytes(fs.readFileSync(abs)) : null,
    };
  });
}
