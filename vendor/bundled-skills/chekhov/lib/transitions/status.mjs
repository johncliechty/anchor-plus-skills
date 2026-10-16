/**
 * STATUS rebuild transition — W1 SKELETON.
 * W10 builds the six-field record and the Ecgberht strip contract; this wave
 * ships the seam: the record is REGENERATED (never hand-kept) and carries a
 * generation digest so a hand edit is detectable (RIDER 4, W10 test).
 * Only lib/engine.mjs may call this module (machine-only-caller test).
 */
import fs from 'node:fs';
import path from 'node:path';
import { sha256Text } from '../manifest.mjs';

export function rebuildStatus(root, { stateDir, project, state, line2 }) {
  const body = {
    schema: 'chekhov-status-v0-skeleton',
    project,
    state,
    line2: line2 || null,
  };
  const digestSource = JSON.stringify(body);
  const record = { ...body, generation_digest: sha256Text(digestSource) };
  fs.mkdirSync(stateDir, { recursive: true });
  const target = path.join(stateDir, 'STATUS.json');
  fs.writeFileSync(target, `${JSON.stringify(record, null, 2)}\n`, 'utf8');
  return { transition: 'status-rebuild', ok: true, path: target, record };
}
