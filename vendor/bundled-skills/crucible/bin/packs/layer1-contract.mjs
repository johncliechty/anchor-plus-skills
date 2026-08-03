// crucible/bin/packs/layer1-contract.mjs — LAYER 1: deterministic doc-contract validator.
//
// Runs with NO model, BEFORE any judge, and returns a 0/1 verdict: does the deliverable
// contain every required section the pack declares? Section presence is matched by the
// section's optional `pattern` (regex, multiline+case-insensitive) or, by default, a
// Markdown heading whose text contains the section title. Pure + deterministic: the same
// (doc, pack) always yields the same verdict.

/**
 * @param {object} o
 * @param {string} o.doc    the deliverable text (e.g. Markdown)
 * @param {object} o.pack   a validated pack (kind:'doc')
 * @returns {{ pass:boolean, exitCode:0|1, missing:{id:string,title:string}[],
 *            present:string[], checked:number }}
 */
export function validateDocContract({ doc, pack }) {
  const text = typeof doc === 'string' ? doc : '';
  const sections = pack?.doc_contract?.required_sections ?? [];
  const missing = [];
  const present = [];
  for (const s of sections) {
    let re;
    if (s.pattern) {
      re = new RegExp(s.pattern, 'im');
    } else {
      // default: a Markdown heading (#..######) whose text contains the section title.
      re = new RegExp(`^#{1,6}\\s*.*${escapeRe(s.title)}`, 'im');
    }
    if (re.test(text)) present.push(s.id);
    else missing.push({ id: s.id, title: s.title });
  }
  const pass = missing.length === 0;
  return { pass, exitCode: pass ? 0 : 1, missing, present, checked: sections.length };
}

function escapeRe(str) {
  return String(str).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * CLI: `node layer1-contract.mjs <pack-id-or-path> <doc-path>` — exits 0 (well-formed)
 * or 1 (missing sections, named on stderr). NO model is ever invoked.
 */
export async function runLayer1Cli(argv, { loadPack, readFile, log = console.error } = {}) {
  const [packRef, docPath] = argv;
  if (!packRef || !docPath) { log('usage: layer1-contract.mjs <pack-id-or-path> <doc-path>'); return 2; }
  const pack = loadPack(packRef);
  const doc = readFile(docPath);
  const r = validateDocContract({ doc, pack });
  if (r.pass) { log(`Layer 1 OK: ${r.checked} required section(s) present (pack ${pack.id})`); return 0; }
  log(`Layer 1 FAIL: missing section(s): ${r.missing.map((m) => `${m.id} ("${m.title}")`).join(', ')}`);
  return 1;
}
