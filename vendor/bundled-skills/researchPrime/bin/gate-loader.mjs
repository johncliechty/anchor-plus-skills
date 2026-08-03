import fs from 'node:fs';
import path from 'node:path';
import { HaltError } from './trio-core/contract-core.mjs';
import { canonicalize, validate } from './governance.mjs';

export function loadGate(runDir) {
  const govPath = path.join(runDir, 'governance.json');
  if (!fs.existsSync(govPath)) {
    throw new HaltError('Execution blocked: governance.json missing');
  }

  const raw = fs.readFileSync(govPath, 'utf8');
  let canon;
  try {
    canon = canonicalize(raw);
  } catch (e) {
    throw new HaltError(`Execution blocked: ${e.message}`);
  }

  const record = canon.canonicalObj;
  
  try {
    validate(record);
  } catch (e) {
    throw new HaltError(`Execution blocked: ${e.message}`);
  }

  if (record.gate1Decision !== 'APPROVE') {
    throw new HaltError(`Execution blocked: Gate 1 decision is ${record.gate1Decision}, expected APPROVE`);
  }
  if (record.gate2Decision !== 'APPROVE') {
    throw new HaltError(`Execution blocked: Gate 2 decision is ${record.gate2Decision}, expected APPROVE`);
  }
  
  return record;
}
