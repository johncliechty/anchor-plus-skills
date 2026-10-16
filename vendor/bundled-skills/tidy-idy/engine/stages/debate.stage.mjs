// engine/stages/debate.stage.mjs — Wave 1: the adversarial review as a stage(ctx).
//
// EXTEND, DON'T FORK: bin/debate.mjs's single-pass Attacker + Judge remains the
// engine; this stage supplies ctx.agent and ctx.northStarFile and converts the
// verdicts into REMOVE findings carrying the verbatim judge rationale (the
// panel renders the verdict verbatim — Wave 6 — so nothing may be paraphrased
// here).
//
// This stage EMITS the only actionable class Wave 1 produces, so it is the
// first place the protection predicate bites: the pipeline filters these
// findings through protection.mjs before they are ever emitted, and every
// withheld path is logged with the reason.
//
// WAVE 2 adds the two gates that stand IN FRONT of the debate, both of which
// run before a model sees anything:
//
//   REMOVAL ELIGIBILITY (owned decision #3). A path git holds an older version
//     of — tracked with staged or unstaged changes — is hard-excluded here,
//     upstream of the attacker/judge pass. The exclusion is not a filter on the
//     verdict; it is a filter on the QUESTION, so no verdict about that path can
//     exist to be approved by accident. Every exclusion carries git's verbatim
//     porcelain line as its evidence.
//
//   THE PRE-LLM SECRET GATE. A flagged path's content never enters the attacker
//     or judge prompt. It is passed to runDebate() as a hard `isAllowed`
//     predicate rather than removed afterwards, because "afterwards" is after
//     the bytes were sent.
//
// And Amendment A changes what a REMOVE verdict MEANS per path: git-held content
// keeps the single-commit + git-revert path; content git does not hold carries
// removalClass 'trash' and applies as a reversible Trash move (Wave 4).

import path from 'node:path';
import { makeStageResult, STATUS } from '../envelope.mjs';
import { runDebate, resolveDebatePasses, resolveTidyIdyKnobs } from '../../bin/debate.mjs';
import { toPosixRel } from '../glob.mjs';
import { loadPorcelain } from '../porcelain.mjs';
import { computeRemovalEligibility, summariseExclusions, REMOVAL_CLASS } from '../eligibility.mjs';
import { ensureHash } from '../snapshot.mjs';

export const debateStage = {
  name: 'debate',
  requiresGit: false,
  gitNull: {
    status: STATUS.OK,
    // Unbounded cap: git presence does not gate this stage's findings (see
    // analyze.stage.mjs for the declaration semantics).
    findings: Number.POSITIVE_INFINITY,
    note: 'no repo — the debate is content-only; git-held-ness gates ELIGIBILITY upstream of it, not the debate itself, and an approved removal applies through the reversible Trash',
  },

  async run(ctx) {
    const suspects = ctx.state.suspects || [];
    const scope = ctx.state.debateScope === 'evidence-sufficiency' ? 'evidence-sufficiency' : 'alignment';

    if (suspects.length === 0) {
      return makeStageResult({
        stage: debateStage.name,
        status: STATUS.OK,
        coverage: {
          scanned: 0,
          skipped: 0,
          errored: 0,
          note: 'no suspects reached the debate — nothing to argue about',
        },
        findings: [],
      });
    }
    if (scope === 'alignment' && ctx.mode !== 'north-star') {
      return makeStageResult({
        stage: debateStage.name,
        status: STATUS.OK,
        coverage: {
          scanned: 0,
          skipped: suspects.length,
          errored: 0,
          note: `mode=${ctx.mode} with no evidence-sufficiency scope set — the alignment debate has no North Star to argue against`,
        },
        findings: [],
      });
    }

    // ---- gate 1: removal eligibility, BEFORE any model call ---------------
    const porcelain = await loadPorcelain(ctx).catch(() => null);
    const blocked = ctx.state.llmBlocked || new Set();
    const candidates = suspects.map((s) => toPosixRel(path.relative(ctx.rootPath, s.filepath)));
    const { eligible, excluded, byPath } = computeRemovalEligibility({
      candidates,
      porcelain,
      secretBlocked: blocked,
    });
    ctx.state.exclusionLog = [...(ctx.state.exclusionLog || []), ...excluded];
    ctx.state.eligibility = byPath;

    const eligiblePaths = new Set(eligible.map((e) => e.path));
    const admitted = suspects.filter((s) => eligiblePaths.has(toPosixRel(path.relative(ctx.rootPath, s.filepath))));

    if (admitted.length === 0) {
      return makeStageResult({
        stage: debateStage.name,
        status: STATUS.OK,
        coverage: {
          scanned: 0,
          skipped: suspects.length,
          errored: 0,
          note: `every candidate was excluded from the REMOVE class before the debate ran — ${summariseExclusions(excluded)}`,
        },
        findings: [],
        notes: [summariseExclusions(excluded), 'excluded paths may still surface as SAVE findings — "git does not hold this yet" argues for committing it, never for deleting it'],
        data: { exclusionLog: excluded },
      });
    }

    // ---- gate 2: the pre-LLM secret gate, as a hard predicate -------------
    // Never skipped on LITE — depth thins ceremony passes only, not protect gates.
    const isAllowed = (abs) => !blocked.has(toPosixRel(path.relative(ctx.rootPath, abs)));

    // B5 P2: forward depth knobs so runDebate resolves debatePasses live
    // (FULL=2, LITE/SPIKE-FIRST=1). Same shared helper as remove/launch.
    const knobOpts = {
      triageDepth: ctx.triageDepth,
      debatePasses: ctx.debatePasses,
      env: ctx.env,
    };
    const debatePasses = resolveDebatePasses(knobOpts);
    const ceremonyKnobs = resolveTidyIdyKnobs(knobOpts);

    // ---- gate 3 (Wave 5): the content-hash verdict cache ------------------
    // Keyed by the bytes, the ruleset version and this scope — never the path —
    // so a re-run after one edit sends exactly that one file to a model and
    // serves the rest from cache. A cache MISS is the only way a verdict is ever
    // produced, and a changed file always misses, so this can shrink the LLM
    // batch but can never change what a verdict about given bytes says.
    const cache = ctx.verdictCache || null;
    const snapshot = ctx.state.snapshot;
    const cached = [];
    const fresh = [];
    for (const s of admitted) {
      const rel = toPosixRel(path.relative(ctx.rootPath, s.filepath));
      let hit = null;
      let contentHash = null;
      if (cache && snapshot && snapshot.paths[rel]) {
        contentHash = await ensureHash(snapshot, rel, { fs: ctx.fs });
        if (contentHash) hit = cache.get({ contentHash, scope });
      }
      if (hit) cached.push({ ...hit, filepath: s.filepath, fromCache: true });
      else fresh.push({ suspect: s, rel, contentHash });
    }

    let judgments;
    try {
      judgments = await runDebate(ctx.rootPath, fresh.map((f) => f.suspect), {
        northStarFile: ctx.northStarFile,
        scope,
        isAllowed,
        agent: ctx.agent,
        // The facade, not raw fs — see analyze.stage.mjs.
        fs: ctx.fs,
        log: ctx.log,
        // Live ceremony knobs (B5 P2) — debatePasses from mapping, never a local table.
        triageDepth: knobOpts.triageDepth,
        debatePasses: knobOpts.debatePasses,
        env: knobOpts.env,
      });
    } catch (err) {
      return makeStageResult({
        stage: debateStage.name,
        status: STATUS.FAILED,
        coverage: { scanned: 0, skipped: suspects.length, errored: 1, note: 'the adversarial review did NOT run — no removal verdict from this run is trustworthy' },
        errors: [{ name: err.name || 'Error', message: err.message }],
        findings: [],
      });
    }

    // Every fresh verdict is stored under the bytes it was made about, and the
    // cached ones are merged back in so downstream code cannot tell (or need to
    // care) which half of the batch came from a model this run.
    if (cache) {
      const byRel = new Map(fresh.map((f) => [toPosixRel(path.relative(ctx.rootPath, f.suspect.filepath)), f]));
      for (const j of judgments) {
        const rel = toPosixRel(path.relative(ctx.rootPath, j.filepath));
        const f = byRel.get(rel);
        if (f && f.contentHash) {
          cache.set({
            contentHash: f.contentHash,
            scope,
            path: rel,
            // The attacker's case is cached WITH the verdict, not separately: a
            // cache hit that produced a judge verdict but lost the case it
            // answered would silently degrade a Wave-6 removal tile from "here
            // is the argument and here is the ruling" to "here is a ruling".
            verdict: { decision: j.decision || j.verdict, rationale: j.rationale || null, attacker: j.attacker || null },
          });
        }
      }
    }
    const allJudgments = [...judgments, ...cached];

    const findings = [];
    let retained = 0;
    for (const j of allJudgments) {
      const decision = String(j.decision || j.verdict || '').toUpperCase();
      if (decision !== 'REMOVE') { retained++; continue; }
      const rel = toPosixRel(path.relative(ctx.rootPath, j.filepath));
      const elig = byPath.get(rel) || null;
      const removalClass = elig && elig.removalClass ? elig.removalClass : REMOVAL_CLASS.TRASH;
      findings.push({
        stage: debateStage.name,
        kind: 'removal-candidate',
        // Amendment A: content git does not hold is removed by a reversible
        // Trash MOVE, not a delete — and the action says so, so the Wave-4
        // executor is selected by the finding rather than by an if-statement
        // somewhere in Apply.
        action: removalClass === REMOVAL_CLASS.GIT ? 'remove' : 'trash',
        removalClass,
        path: rel,
        absolutePath: j.filepath,
        trackingClass: elig ? elig.trackingClass : null,
        porcelain: elig ? elig.porcelain : null,
        debateScope: scope,
        undo: removalClass === REMOVAL_CLASS.GIT
          ? 'git revert of the single tidy commit'
          : 'restore-from-Trash — the file is MOVED into .tidy-idy/trash/<run-id>/, never deleted (Amendment A)',
        ...(scope === 'evidence-sufficiency' ? { label: 'heuristic candidate', defaultChecked: false } : {}),
        // Verbatim — the panel shows the judge's own words, not a summary, and
        // the attacker's case beside them so the tile carries the ARGUMENT and
        // the RULING rather than a verdict a reader has to take on trust. Null
        // when the attacker pass produced nothing for this file; the tile says
        // so rather than implying a case was made.
        evidence: {
          decision,
          rationale: j.rationale || null,
          attacker: j.attacker || null,
          eligibility: elig ? elig.why : null,
        },
      });
    }

    return makeStageResult({
      stage: debateStage.name,
      status: STATUS.OK,
      coverage: {
        scanned: admitted.length,
        // Excluded candidates are NOT a coverage gap: they were answered, and
        // the answer was "this path is not removable". Recording them as skipped
        // would make a correct, complete run look partial forever.
        skipped: 0,
        errored: 0,
        note: `${admitted.length} eligible candidate(s) judged in ${scope} scope (${fresh.length} sent to the model, ${cached.length} served from the verdict cache); ${summariseExclusions(excluded)}`,
      },
      findings,
      notes: [
        `${findings.length} REMOVE verdict(s), ${retained} RETAIN verdict(s) — RETAIN is the fail-safe default at every failure point`,
        ...(cache
          ? [`verdict cache: ${cached.length} hit(s), ${fresh.length} miss(es) — the cache is keyed by CONTENT HASH + ruleset version + scope, so an edited file always misses and no verdict can be served for bytes it was not made about`]
          : []),
        summariseExclusions(excluded),
        `${findings.filter((f) => f.removalClass === REMOVAL_CLASS.TRASH).length} of the REMOVE verdict(s) apply as a reversible Trash move (git does not hold that content); the rest apply inside the single tidy commit`,
        ...(scope === 'evidence-sufficiency' ? ['debate re-scoped to EVIDENCE SUFFICIENCY — there is no North-Star document here, so the judge was asked whether the raw evidence justifies removal, not whether the file serves an objective nobody stated'] : []),
      ],
      data: {
        exclusionLog: excluded,
        scope,
        // B5 P2: observed ceremony pass count from live knobs (not a hard-coded table).
        debatePasses,
        ceremonyKnobs: ceremonyKnobs
          ? {
              debatePasses: ceremonyKnobs.debatePasses,
              maxRemovalsPerBatch: ceremonyKnobs.maxRemovalsPerBatch,
            }
          : null,
        verdictCache: cache ? { hits: cached.length, misses: fresh.length, sentToModel: fresh.map((f) => f.rel) } : null,
      },
    });
  },
};

export default debateStage;
