import fs from 'node:fs';
import { runLiveRefutation, buildLiveRefuterAgent } from './runtime/live-refuter.mjs';
import { createCommissionLedger } from './seam/commission-ledger.mjs';

const draft = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
draft.elevations = draft.elevations.filter(e => ['e-1','e-2','e-3','e-4'].includes(e.id));
const ledger = createCommissionLedger();
const agent = await buildLiveRefuterAgent({});
const out = await runLiveRefutation(draft, { budget: 4, ledger, agent, log: m => console.error(m) });
const els = out?.draft?.elevations ?? out?.elevations ?? draft.elevations;
for (const e of els) {
  const p = e.refutation_provenance;
  console.log('=== ' + e.id + ' | rung=' + e.rung + ' | tier=' + (e.tier ?? '-'));
  if (p) {
    console.log('SURVIVED: ' + p.survived);
    console.log('DEFEATER: ' + p.defeater);
    console.log('VERDICT : ' + p.verdict);
  } else console.log('(no provenance)');
  console.log('');
}
