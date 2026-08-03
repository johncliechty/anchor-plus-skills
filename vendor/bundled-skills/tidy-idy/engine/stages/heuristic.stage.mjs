// engine/stages/heuristic.stage.mjs — Wave 2: honest findings without a North Star.
//
// A folder with no NORTH-STAR.md / INTENT.md / SKILL.md has no stated objective,
// so there is nothing for an alignment analysis to align against. The Wave-0
// inventory recorded what the old code did about that: it THREW, which made an
// ordinary folder invisible to the tool. Wave 1 turned that into a MODE. This
// stage is what that mode actually does.
//
// The evidence here is materially weaker than an argued North-Star mismatch —
// "this file is old" is a fact about a timestamp, not an argument — and the
// design refuses to launder that difference:
//
//   • every finding is LABELLED 'heuristic candidate';
//   • every finding carries its RAW EVIDENCE verbatim (the mtime, the sibling
//     that shares its hash, the zero reference hits, git's porcelain line);
//   • every finding DEFAULTS TO UNCHECKED, so bulk-approve can never mean
//     "delete everything that looked old";
//   • the debate that follows is RE-SCOPED: it argues whether the evidence is
//     SUFFICIENT, not whether the file serves an objective nobody wrote down.
//
// Four heuristics, each independently attributable on the finding:
//   age            — untouched for longer than the age threshold
//   duplicate-hash — byte-identical to another in-scope file
//   orphan         — its basename appears in no other text file in the tree
//   untracked      — git does not hold it (only when there is a repo)

import path from 'node:path';
import { makeStageResult, STATUS } from '../envelope.mjs';
import { ensureHash } from '../snapshot.mjs';
import { loadPorcelain, TRACKING } from '../porcelain.mjs';
import { LLM_READ_CAP_BYTES } from '../secret-triage.mjs';

/** A file untouched for this long is old enough to be worth a look. */
export const AGE_THRESHOLD_DAYS = 180;

/** Extensions worth reference-scanning; the scan is textual and cheap. */
const REFERENCE_SCAN_CAP_BYTES = 512 * 1024;

export const heuristicStage = {
  name: 'heuristic',
  requiresGit: false,
  gitNull: {
    status: STATUS.OK,
    // Three of the four heuristics are filesystem-only; only 'untracked' needs
    // git, and its absence removes evidence rather than adding behaviour.
    findings: Number.POSITIVE_INFINITY,
    note: 'no repo — the age/duplicate-hash/orphan heuristics run unchanged; the untracked heuristic simply has no evidence to contribute',
  },

  async run(ctx) {
    if (ctx.mode === 'north-star') {
      return makeStageResult({
        stage: heuristicStage.name,
        status: STATUS.OK,
        coverage: {
          scanned: 0,
          skipped: 0,
          errored: 0,
          note: `mode=${ctx.mode}: a North-Star document exists, so candidate selection is the analyze stage's argued alignment judgement rather than raw file heuristics`,
        },
        findings: [],
        notes: ['heuristic mode not engaged — this folder states its objective, so findings are argued against it instead of inferred from timestamps'],
      });
    }

    const inScope = (ctx.state.inScope || []).filter((rel) => !ctx.protection.isProtected(rel));
    const snapshot = ctx.state.snapshot;
    const blocked = ctx.state.llmBlocked || new Set();
    const porcelain = await loadPorcelain(ctx).catch(() => null);
    const now = ctx.now ? ctx.now().getTime() : Date.now();

    const evidence = new Map();
    const note = (rel, key, value) => {
      if (!evidence.has(rel)) evidence.set(rel, {});
      evidence.get(rel)[key] = value;
    };

    // --- age ---------------------------------------------------------------
    for (const rel of inScope) {
      const meta = snapshot && snapshot.paths ? snapshot.paths[rel] : null;
      if (!meta) continue;
      const ageDays = (now - meta.mtimeMs) / 86400000;
      if (ageDays >= AGE_THRESHOLD_DAYS) {
        note(rel, 'age', {
          heuristic: 'age',
          mtimeMs: meta.mtimeMs,
          mtimeIso: new Date(meta.mtimeMs).toISOString(),
          ageDays: Math.floor(ageDays),
          thresholdDays: AGE_THRESHOLD_DAYS,
          raw: `mtime=${new Date(meta.mtimeMs).toISOString()} (${Math.floor(ageDays)} days ago; threshold ${AGE_THRESHOLD_DAYS})`,
        });
      }
    }

    // --- duplicate hash ----------------------------------------------------
    const errors = [];
    const byHash = new Map();
    if (snapshot) {
      for (const rel of inScope) {
        const meta = snapshot.paths ? snapshot.paths[rel] : null;
        if (!meta || meta.size === 0 || meta.size > LLM_READ_CAP_BYTES) continue;
        let h = null;
        try { h = await ensureHash(snapshot, rel, { fs: ctx.fs }); } catch { h = null; }
        if (!h) continue;
        if (!byHash.has(h)) byHash.set(h, []);
        byHash.get(h).push(rel);
      }
      for (const [hash, group] of byHash) {
        if (group.length < 2) continue;
        for (const rel of group) {
          note(rel, 'duplicate-hash', {
            heuristic: 'duplicate-hash',
            contentHash: hash,
            duplicates: group.filter((g) => g !== rel),
            raw: `sha256 ${hash} is shared byte-for-byte with: ${group.filter((g) => g !== rel).join(', ')}`,
          });
        }
      }
    }

    // --- orphan (no textual reference anywhere else in the tree) -----------
    const referenced = new Set();
    let unreadableRefs = 0;
    for (const rel of inScope) {
      const meta = snapshot && snapshot.paths ? snapshot.paths[rel] : null;
      if (meta && meta.size > REFERENCE_SCAN_CAP_BYTES) continue;
      if (blocked.has(rel)) continue; // never read blocked content for any purpose
      let text;
      try {
        text = await ctx.fs.readFile(path.join(ctx.rootPath, rel), 'utf8');
      } catch { unreadableRefs++; continue; }
      if (text.includes(String.fromCharCode(0))) continue; // binary: not a reference source
      for (const other of inScope) {
        if (other === rel) continue;
        if (referenced.has(other)) continue;
        const base = other.split('/').pop();
        if (base && (text.includes(other) || text.includes(base))) referenced.add(other);
      }
    }
    for (const rel of inScope) {
      if (referenced.has(rel)) continue;
      note(rel, 'orphan', {
        heuristic: 'orphan',
        referenceHits: 0,
        raw: `a whole-tree textual scan of ${inScope.length} in-scope file(s) found no occurrence of '${rel}' or of its basename in any other file`,
      });
    }

    // --- untracked (git only) ---------------------------------------------
    if (porcelain) {
      for (const rel of porcelain.untracked()) {
        if (!inScope.includes(rel)) continue;
        const rec = porcelain.record(rel);
        note(rel, 'untracked', {
          heuristic: 'untracked',
          trackingClass: TRACKING.UNTRACKED,
          raw: rec ? rec.raw : null,
        });
      }
    }

    // --- emission ----------------------------------------------------------
    // A single weak signal is noise. Requiring TWO independent heuristics is the
    // cheapest defence against a precision collapse in a mode whose evidence is
    // already the weakest the tool produces (the Wave-9 gate measures it).
    const findings = [];
    for (const [rel, ev] of evidence) {
      const heuristics = Object.keys(ev);
      if (heuristics.length < 2) continue;
      if (blocked.has(rel)) continue;
      findings.push({
        stage: heuristicStage.name,
        kind: 'heuristic-candidate',
        action: 'remove',
        label: 'heuristic candidate',
        path: rel,
        absolutePath: path.join(ctx.rootPath, rel),
        /** Default-UNCHECKED is a safety property, not a UI preference. */
        defaultChecked: false,
        bulkApprovable: false,
        heuristics,
        // Raw and verbatim: the panel shows the timestamp / the hash / the zero
        // hit count itself, so a human can disagree with the inference.
        evidence: ev,
        evidenceNote: 'no North-Star document exists for this folder, so this finding rests on raw file evidence rather than on an argued relationship to a stated objective',
        why: `matched ${heuristics.length} independent heuristics (${heuristics.join(' + ')}) — evidence, not a verdict`,
      });
    }

    // The debate consumes these next, RE-SCOPED to evidence sufficiency.
    if (findings.length) {
      ctx.state.suspects = [
        ...(ctx.state.suspects || []),
        ...findings.map((f) => ({
          filepath: f.absolutePath,
          reason: `heuristic candidate — ${f.why}. Raw evidence: ${Object.values(f.evidence).map((e) => e.raw).filter(Boolean).join(' | ')}`,
        })),
      ];
      ctx.state.debateScope = 'evidence-sufficiency';
    }

    return makeStageResult({
      stage: heuristicStage.name,
      status: errors.length ? STATUS.PARTIAL : STATUS.OK,
      coverage: {
        scanned: inScope.length,
        skipped: 0,
        errored: errors.length,
        note: `${inScope.length} unprotected in-scope path(s) evaluated against 4 heuristics${unreadableRefs ? `; ${unreadableRefs} file(s) could not be read for the reference scan` : ''}`,
      },
      errors,
      findings,
      notes: [
        `mode=${ctx.mode}: ${findings.length} heuristic candidate(s), every one labelled and default-UNCHECKED`,
        'a candidate needs TWO independent heuristics to be emitted at all — a single weak signal is noise, and this mode\'s precision is measured against the labeled corpus by the Wave-9 gate',
        ...(findings.length ? ['the debate that follows is re-scoped to argue EVIDENCE SUFFICIENCY, not North-Star alignment (there is no North Star here to align against)'] : []),
      ],
      data: { referencedCount: referenced.size, duplicateGroups: [...byHash.values()].filter((g) => g.length > 1).length },
    });
  },
};

export default heuristicStage;
