// tools/w0-packet.mjs — the blind packet page for John: every candidate from Wave 0 and the lean
// controls, letters only, mode/effort/domain/verdict hidden. Usage: node tools/w0-packet.mjs <out.html>
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROTO = path.resolve(HERE, '..', 'planning', 'crucible-2026-09-14', 'proto');
const CMP = path.resolve(HERE, '..', '..', 'jumper', 'planning', 'review-2026-09-13', 'comparison', 'briefs');
const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const blind = JSON.parse(fs.readFileSync(path.join(PROTO, 'blind', 'items.json'), 'utf8'));
const briefs = { teaching: fs.readFileSync(path.join(CMP, 'teaching-einstein-cover.txt'), 'utf8'), artifact: fs.readFileSync(path.join(CMP, 'artifact-book1-victories.md'), 'utf8') };
const block = (brief, title, ask) => {
  const items = blind.filter((b) => b.brief === brief);
  return `<section><h2>${esc(title)}</h2><p class="ask">${esc(ask)}</p><details><summary>The brief, verbatim</summary><pre class="deliv">${esc(briefs[brief])}</pre></details>
<div class="mark"><b>Your marks:</b> for each letter, say <i>useful</i>, <i>novel</i>, <i>both</i>, or <i>neither</i>. Useful = you would take it as delivered or with light editing. Novel = an idea you had not already had.</div>
${items.map((b) => `<article class="cand"><h3>${esc(b.letter)}</h3><details open><summary>The candidate</summary><pre class="deliv">${esc(b.deliverable)}</pre></details>${b.weakness ? `<p class="meta"><b>Its own stated weakness</b> ${esc(b.weakness)}</p>` : ''}${b.test ? `<p class="meta"><b>Its proposed test (unperformed)</b> ${esc(b.test)}</p>` : ''}</article>`).join('')}</section>`;
};
const page = `<title>Superjump Blind Packet</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{color-scheme:light;--paper:#F3F5F7;--paper-2:#E9EDF1;--ink:#1B2430;--ink-2:#5B6672;--rule:#D3DAE1;--accent:#2A6F8C;--accent-ink:#1F5468;--serif:"Fraunces","Iowan Old Style",Georgia,serif;--sans:"IBM Plex Sans","Segoe UI",system-ui,sans-serif;--mono:"IBM Plex Mono",Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--paper:#12171C;--paper-2:#1A2128;--ink:#E6EAEE;--ink-2:#98A3AE;--rule:#2A333D;--accent:#6FB3CF;--accent-ink:#8FC6DC}}
:root[data-theme="dark"]{color-scheme:dark;--paper:#12171C;--paper-2:#1A2128;--ink:#E6EAEE;--ink-2:#98A3AE;--rule:#2A333D;--accent:#6FB3CF;--accent-ink:#8FC6DC}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.55;margin:0}
.page{max-width:900px;margin:0 auto;padding:44px 24px 96px}
.eyebrow{font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--accent-ink);margin:0 0 10px}
h1{font-family:var(--serif);font-variation-settings:"opsz" 144;font-weight:600;font-size:clamp(32px,4.4vw,48px);line-height:1.06;margin:0 0 14px;text-wrap:balance}
h2{font-family:var(--serif);font-weight:600;font-size:27px;margin:48px 0 6px}
h3{font-family:var(--serif);font-weight:600;font-size:24px;margin:0 0 8px;color:var(--accent-ink)}
p{margin:0 0 12px;text-wrap:pretty}
.dek{font-size:18px;color:var(--ink-2);max-width:64ch;margin:0}
header{border-bottom:1px solid var(--rule);padding-bottom:24px;margin-bottom:26px}
.ask{color:var(--ink-2);margin:0 0 10px}
.mark{background:var(--paper-2);padding:12px 16px;border-radius:6px;margin:12px 0 18px;font-size:15px}
.cand{padding:16px 0 10px;border-top:1px solid var(--rule)}
details{margin:6px 0}summary{cursor:pointer;color:var(--accent-ink);font-weight:500;font-size:14px}
pre.deliv{white-space:pre-wrap;overflow-wrap:anywhere;font-family:var(--sans);font-size:14.5px;line-height:1.5;background:var(--paper-2);padding:12px 14px;border-radius:5px;margin:8px 0 6px;max-height:560px;overflow:auto}
.meta{font-size:14px;margin:6px 0}.meta b{font-weight:600;margin-right:4px}
footer{margin-top:52px;padding-top:16px;border-top:1px solid var(--rule);font-size:13.5px;color:var(--ink-2)}
</style>
<div class="page">
<header><p class="eyebrow">Skill Foundry · Superjump · Wave 0 · blind packet</p><h1>Twenty-one candidates, two briefs, no labels</h1>
<p class="dek">Every candidate produced yesterday and today on these two briefs, by either engine at any effort, in a fixed random order. Nothing here says which engine, which effort, which foreign domain, or what the reviewer decided. Mark each letter; the mapping is sealed in a separate file until you have.</p></header>
${block('teaching', 'Teaching brief — a classroom storyboard for the finite-cover bottleneck', 'One short storyboard: exact question, learner prediction, two or three visual states, the mathematical limitation, a comprehension check. No metaphor-heavy narrative.')}
${block('artifact', 'Book 1 brief — three concrete victories for John to refine', 'Each candidate is one proposed ending for author discussion, never approved canon; each should make the victory concrete and legible to a young reader.')}
<footer><p>How to answer: reply with the letters and your marks, e.g. "TA both, TB neither, … BA useful …". After that the mapping is opened and the calibration report is finished with your judgment in it.</p></footer>
</div>
`;
fs.writeFileSync(process.argv[2], page);
console.log('bytes', page.length, 'items', blind.length);
