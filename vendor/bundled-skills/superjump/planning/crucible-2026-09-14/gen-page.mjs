// gen-page.mjs — render the Superjump plan packet (analysis, adversarial read, plan, icons) as one page.
// Usage: node gen-page.mjs <out.html>   (run from planning/crucible-2026-09-14)
import fs from 'node:fs';
const esc = (s) => String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const b64 = (p) => 'data:image/png;base64,' + fs.readFileSync(p).toString('base64');
const icon1 = b64('../../assets/superjump-icon-256.png');
const icon2 = b64('../../assets/superjump-icon-v2-256.png');
const md = (p) => fs.readFileSync(p, 'utf8');
// minimal markdown → html for the plan docs (headings, paragraphs, lists, tables, code, bold/code spans)
function mdToHtml(src) {
  const lines = src.split('\n'); let out = ''; let inList = null; let inCode = false; let inTable = false; let para = [];
  const inline = (t) => esc(t).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/\*([^*]+)\*/g, '<i>$1</i>');
  const flushPara = () => { if (para.length) { out += `<p>${inline(para.join(' '))}</p>`; para = []; } };
  const closeList = () => { if (inList) { out += `</${inList}>`; inList = null; } };
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '');
    if (line.startsWith('```')) { flushPara(); closeList(); if (inCode) { out += '</pre>'; inCode = false; } else { out += '<pre class="code">'; inCode = true; } continue; }
    if (inCode) { out += esc(line) + '\n'; continue; }
    if (/^\|/.test(line)) { flushPara(); closeList(); if (/^\|\s*-+/.test(line)) continue; const cells = line.split('|').slice(1, -1).map((c) => c.trim()); if (!inTable) { out += '<div class="tablewrap"><table><thead><tr>' + cells.map((c) => `<th>${inline(c)}</th>`).join('') + '</tr></thead><tbody>'; inTable = true; } else { out += '<tr>' + cells.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>'; } continue; }
    if (inTable) { out += '</tbody></table></div>'; inTable = false; }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) { flushPara(); closeList(); const lvl = Math.min(h[1].length + 1, 4); out += `<h${lvl}>${inline(h[2])}</h${lvl}>`; continue; }
    if (/^>\s?/.test(line)) { continue; }
    const li = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(line);
    if (li) { flushPara(); const kind = /\d/.test(li[2]) ? 'ol' : 'ul'; if (inList !== kind) { closeList(); out += `<${kind}>`; inList = kind; } out += `<li>${inline(li[3])}</li>`; continue; }
    if (!line.trim()) { flushPara(); closeList(); continue; }
    if (/^---/.test(line)) { flushPara(); closeList(); continue; }
    para.push(line);
  }
  flushPara(); closeList(); if (inTable) out += '</tbody></table></div>'; if (inCode) out += '</pre>';
  return out;
}
const analysis = md('ANALYSIS.md'); const review = md('chatgpt-review/REVIEW-CHATGPT.md');
const ns = md('NORTH-STAR.md'); const master = md('MASTER-PLAN.md'); const impl = md('IMPLEMENTATION-PLAN.md');
const section = (title, body, open) => `<details class="doc" ${open ? 'open' : ''}><summary><h2>${esc(title)}</h2></summary><div class="docbody">${body}</div></details>`;
const page = `<title>Superjump Plan</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{color-scheme:light;--paper:#F3F5F7;--paper-2:#E9EDF1;--ink:#1B2430;--ink-2:#5B6672;--rule:#D3DAE1;--accent:#2A6F8C;--accent-ink:#1F5468;--gold:#B8860B;--serif:"Fraunces","Iowan Old Style",Georgia,serif;--sans:"IBM Plex Sans","Segoe UI",system-ui,sans-serif;--mono:"IBM Plex Mono",Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--paper:#12171C;--paper-2:#1A2128;--ink:#E6EAEE;--ink-2:#98A3AE;--rule:#2A333D;--accent:#6FB3CF;--accent-ink:#8FC6DC;--gold:#E0B04A}}
:root[data-theme="dark"]{color-scheme:dark;--paper:#12171C;--paper-2:#1A2128;--ink:#E6EAEE;--ink-2:#98A3AE;--rule:#2A333D;--accent:#6FB3CF;--accent-ink:#8FC6DC;--gold:#E0B04A}
body{background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.55;margin:0}
.page{max-width:1040px;margin:0 auto;padding:44px 24px 96px}
.measure{max-width:70ch}
.eyebrow{font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--accent-ink);margin:0 0 10px}
h1{font-family:var(--serif);font-variation-settings:"opsz" 144;font-weight:600;font-size:clamp(34px,4.6vw,52px);line-height:1.06;margin:0 0 14px;text-wrap:balance;letter-spacing:-.01em}
h2{font-family:var(--serif);font-variation-settings:"opsz" 72;font-weight:600;font-size:27px;margin:0;text-wrap:balance;display:inline}
h3{font-family:var(--serif);font-weight:600;font-size:21px;margin:26px 0 8px}
h4{font-size:16px;font-weight:600;margin:20px 0 6px}
p{margin:0 0 12px;text-wrap:pretty}
ul,ol{padding-left:22px;margin:0 0 12px}li{margin:0 0 6px}
code{font-family:var(--mono);font-size:.88em;background:var(--paper-2);padding:1px 5px;border-radius:3px}
pre.code{font-family:var(--mono);font-size:13.5px;background:var(--paper-2);padding:12px 14px;border-radius:5px;overflow-x:auto;margin:8px 0 14px}
.dek{font-size:18.5px;color:var(--ink-2);max-width:62ch;margin:0}
.meta-row{display:flex;flex-wrap:wrap;gap:6px 22px;margin-top:16px;font-family:var(--mono);font-size:12.5px;color:var(--ink-2)}
.meta-row b{color:var(--ink);font-weight:500}
header{border-bottom:1px solid var(--rule);padding-bottom:26px;margin-bottom:34px}
ol.findings{counter-reset:f;list-style:none;padding:0;display:grid;gap:12px;margin:0 0 8px}
ol.findings li{position:relative;padding-left:42px}
ol.findings li::before{counter-increment:f;content:counter(f);position:absolute;left:0;top:1px;width:27px;height:27px;border:1.5px solid var(--accent);border-radius:50%;color:var(--accent-ink);font-family:var(--serif);font-weight:600;font-size:14px;display:grid;place-items:center}
ol.findings b{display:block;font-weight:600;margin-bottom:2px}
table{border-collapse:collapse;width:100%;font-size:14.5px;margin:10px 0 14px}
th{text-align:left;font-weight:600;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink-2);padding:8px 10px 8px 0;border-bottom:1px solid var(--rule)}
td{padding:9px 10px 9px 0;border-bottom:1px solid var(--rule);vertical-align:top}
.tablewrap{overflow-x:auto}
details.doc{border-top:1px solid var(--rule);padding:18px 0 6px;margin-top:8px}
details.doc summary{cursor:pointer;list-style:none;display:flex;align-items:baseline;gap:12px}
details.doc summary::before{content:"▸";color:var(--accent-ink);font-size:18px}
details.doc[open] summary::before{content:"▾"}
.docbody{padding:10px 0 8px;max-width:78ch}
.docbody h2{display:block;font-size:22px;margin:22px 0 8px}
.icons{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:22px;margin:14px 0 8px}
.icon{text-align:center}
.icon img{width:256px;max-width:100%;border-radius:12px;background:#000;display:block;margin:0 auto 8px}
.icon p{font-size:14px;color:var(--ink-2)}
.decision{margin:36px 0 0;padding:20px 24px;background:var(--paper-2);border-radius:6px}
.decision h2{display:block;margin:0 0 8px;font-size:25px}
.decision p:last-child{margin:0}
footer{margin-top:52px;padding-top:16px;border-top:1px solid var(--rule);font-size:13.5px;color:var(--ink-2)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
</style>
<div class="page">
<header>
<p class="eyebrow">Skill Foundry · Superjump · Stage 0–2 plan</p>
<h1>Superjump: the original structure, delivered against a clock you can see</h1>
<p class="dek">Jumper stays lean. Superjump keeps the read, the SCAMPER scan, the leap into a foreign domain, the TRIZ resolution, the three gates and the fair test, and judges every idea in your brief's own terms. A Fable analysis, an adversarial ChatGPT read, and a consolidated Crucible-shaped plan, in that order.</p>
<div class="meta-row"><span>date <b>2026-09-14</b></span><span>status <b>planned, not built</b></span><span>reviewer <b>ChatGPT gpt-6-astra, ultra</b></span><span>on disk <b>skills/superjump/planning/crucible-2026-09-14/</b></span></div>
</header>

<section class="measure">
<h3 style="margin-top:0">What the analysis and the adversarial read settled</h3>
<ol class="findings">
<li><b>Why Jumper timed out.</b> Wrong clocks (fixed yesterday) and ten model calls in a row at the highest effort. Patience makes the chain finish; it does not make it fast.</li>
<li><b>What the clock allows.</b> A generation call costs three to ten minutes, a review about five. At most three hops can run in sequence, so the seven stages fold into Read, Leap and Judge, with the leap's transfer written as an inspectable trace.</li>
<li><b>The five-to-ten-minute promise did not survive review, and you removed the clock altogether.</b> The critical path is the read plus the slowest candidate's generation plus its review: twelve minutes at the default boxes, eleven to twenty on measured proxies at highest effort. Your decision: no time limit of any kind. The engine states what to expect from measured runs, watches each seat for observable progress (the CLI's own output stream where it streams; the calibrated range where it does not), writes results as they land, and only recommends a kill when progress has stopped well past the longest run ever seen to finish. The kill is yours or the steward's; a generous, recorded safety timeout against a hung process is the only automatic stop.</li>
<li><b>The fit metric is three things, not one number.</b> Eligibility from explicit lines in the brief (violations kill, with the passage); anchored ratings on the judging axes you can reweight after the run; duplicates grouped as one idea. Deterministic phrase checks are labelled lints. The reviewer never sees a self-score and re-checks the contract against the brief first.</li>
<li><b>Ceremony cut before structure.</b> The read and SCAMPER stay because you asked for them; the fixed five-sphere taxonomy becomes a hint; self-scores, pairwise distinctness judgments, analogy quality in the ranking, the Synthesizer and the refuter lane on the read are gone.</li>
<li><b>Measure before building.</b> Wave 0 is a prototype run with prompts only, judged blind by you against Jumper's lean mode on two briefs, at two effort settings. If it does not earn its cost there, the engine is not built.</li>
</ol>
</section>

<section class="measure">
<h3>The icon</h3>
<div class="icons">
<div class="icon"><img src="${icon1}" alt="Superjump icon variant 1: the Jumper tiger in the crystal ball with a warm burst of light rays from its centre"><p>v1 — warm burst, brighter core</p></div>
<div class="icon"><img src="${icon2}" alt="Superjump icon variant 2: the same tiger with thinner rays and the figure kept crisp"><p>v2 — thin rays, tiger kept crisp</p></div>
</div>
</section>

${section('North Star (Stage 0, to lock on your word)', mdToHtml(ns), true)}
${section('Master Plan (Stage 1)', mdToHtml(master), false)}
${section('Implementation Plan (Stage 2)', mdToHtml(impl), false)}
${section('The deep analysis (Fable)', mdToHtml(analysis), false)}
${section('The adversarial read (ChatGPT)', mdToHtml(review), false)}

<section class="measure">
<div class="decision"><p class="eyebrow">The one decision</p><h2>Confirm the revised plan — progress observed, no clock — and start Wave 0?</h2><p>You approved the plan and the strategy and asked for one change: no artificial time limit, watch for real progress, only recommend a kill. That change is now in the North Star (NG-2 "kill on a clock", NG-8 "hide a stall"), the analysis (§11), and both plans (the progress monitor, progressive results, the operator's control-file kill, a recorded 60-minute safety timeout as the only automatic stop). Yes locks the North Star and starts Wave 0: a prompts-only prototype on two briefs at two effort settings, which also records what each model's CLI streams while it works, judged blind by you against lean mode before any engine is built. The icon choice (v1 or v2) is a separate, later question.</p></div>
</section>
<footer><p class="measure">Evidence: Jumper journals 0001–0058, the 2026-09-13 review, the six-run comparison logs (single observations per stage, not distributions). ChatGPT's read ran on the inlined material at ultra effort; its six revisions are adopted in ANALYSIS.md §10 and reflected in the three plan documents. No Superjump code exists. Journal 0001 in skills/superjump/journal/.</p></footer>
</div>
`;
fs.writeFileSync(process.argv[2], page);
console.log('bytes', page.length);
