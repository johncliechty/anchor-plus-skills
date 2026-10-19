// engine/stages/scan.stage.mjs — Wave 1: enumeration as a stage(ctx).
//
// The Wave-0 inventory recorded scanner.mjs's foundry-marker-assumption:
// scan(<plain folder>) returned [], so an ordinary folder was INVISIBLE to the
// whole pipeline and every downstream stage silently no-opped on it. The fix
// from that record's proposed-fix field: ctx.rootPath IS the target. Marker
// detection selects ctx.mode (done in engine/context.mjs); it never decides
// whether the folder exists as far as the tool is concerned.
//
// This stage does not re-walk the tree: the topology check already produced the
// authoritative in-scope list (root minus excluded subtrees minus reportDir),
// and having exactly ONE enumeration is what lets snapshot S, the findings and
// Apply all talk about the same set of paths.

import { makeStageResult, STATUS } from '../envelope.mjs';

export const scanStage = {
  name: 'scan',
  requiresGit: false,
  gitNull: {
    status: STATUS.OK,
    findings: 0,
    note: 'no repo — enumeration is filesystem-only and unaffected',
  },

  async run(ctx) {
    const topo = ctx.state.topology;
    if (!topo) {
      throw new Error('scan stage ran before the topology check — the pipeline must establish the in-scope set first');
    }

    const inScope = topo.inScope || [];
    ctx.state.inScope = inScope;

    const notes = [
      `mode=${ctx.mode}${ctx.northStarFile ? ` (North-Star: ${ctx.northStarFile})` : ' (no North-Star marker — heuristics label their findings)'}`,
      `${inScope.length} file(s) in scope under ${ctx.rootPath}`,
    ];
    if (topo.excludedSubtrees.length) {
      notes.push(`${topo.excludedSubtrees.length} excluded subtree(s)/path(s) recorded in the envelope — the run states what it did NOT look at`);
    }
    if (topo.links.length) {
      notes.push(`${topo.links.length} link object(s) recorded, none followed`);
    }

    const errored = (topo.errors || []).filter((e) => e.kind === 'unreadable-dir').length;
    return makeStageResult({
      stage: scanStage.name,
      status: errored ? STATUS.PARTIAL : STATUS.OK,
      // COVERAGE SEMANTICS (uniform across stages): `skipped` counts IN-SCOPE
      // work the stage declined to do — the honest coverage gap that must keep
      // a run from rendering as clean. Policy EXCLUSIONS (.git, node_modules,
      // nested repos, the exclusion set) are not gaps; they are recorded
      // separately as topology.excludedSubtrees so the envelope still states
      // exactly what was not looked at.
      coverage: {
        scanned: inScope.length,
        skipped: 0,
        errored,
        note: errored
          ? `${errored} directory/directories could not be read; ${topo.excludedSubtrees.length} path(s) excluded by policy`
          : `${topo.excludedSubtrees.length} path(s) excluded by policy (listed in topology.excludedSubtrees)`,
      },
      errors: errored
        ? (topo.errors || []).filter((e) => e.kind === 'unreadable-dir').map((e) => ({ message: `unreadable directory '${e.path}': ${e.message}` }))
        : [],
      findings: [],
      notes,
      data: { inScope },
    });
  },
};

export default scanStage;
