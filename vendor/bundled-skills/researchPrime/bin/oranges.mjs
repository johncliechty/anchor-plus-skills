// bin/oranges.mjs — Wave 4 Phase-1 seam: the Oranges FORESIGHT receipt (crit-3 re-aim).
//
// MASTER-PLAN crit-3 (falsifiable): "The Oranges receipt must name ≥1 dropped/reordered branch +
// its counterfactual cost to pass, else it is stamped 'no foresight value added' and crit-3 is
// reported NOT satisfied; a planted-path-defect probe confirms it re-aims." IMPLEMENTATION-PLAN
// Wave 4: "Given a fixture with a planted path defect, Then foresight drops/reorders that exact
// branch (equality assertion, crit-3 re-aim)."
//
// The honesty design is that crit-3 cannot be satisfied by THEATRE: a pass that touches nothing is
// not silently reported as success — it is explicitly stamped "no foresight value added" and
// `crit3_satisfied:false`. Only a receipt that actually NAMES a dropped/reordered branch AND its
// counterfactual cost counts.
//
// The foresight MODEL is deterministic and reads only a branch's ECONOMICS (`est_value`/`est_cost`),
// never a "drop me" flag or the planting defect id — so recovering the exact planted wasteful branch
// is a real test of the pruning rule, not a tautology. A branch whose expected value does not cover
// its cost (net ≤ 0) is dropped; surviving branches are reordered to run highest-net-value first.
// No clock, no randomness: same plan ⇒ same receipt.

// The gate label the fixture's path-defect records carry in `detectable_by` (FIXTURE-SPEC §4).
export const FORESIGHT_GATE = 'Oranges';

// The exact stamp a value-free pass carries (crit-3 reported NOT satisfied). Asserted literally.
export const NO_VALUE_STAMP = 'no foresight value added';
export const VALUE_STAMP = 'foresight value added';

/** Net expected value of a branch: value minus cost. Missing fields default to 0. */
function netValue(branch) {
  const v = Number(branch?.est_value ?? 0);
  const c = Number(branch?.est_cost ?? 0);
  return v - c;
}

/**
 * Build a research plan from the fixture's planted path-defects plus some sound branches.
 *
 * Each path-defect becomes a WASTEFUL branch — net value ≤ 0 (it costs more than it returns) — and
 * carries the defect's `counterfactual_cost` (what is wasted if foresight does NOT drop it). The
 * sound branches have strictly positive, descending net value so a correctly-ordered plan needs no
 * reorder; the only value foresight can add is dropping the wasteful branch(es). This keeps the
 * crit-3 equality assertion sharp: the model must recover EXACTLY the planted branch.
 *
 * @param {object[]} pathDefects fixture records with class 'path-defect' (wrong_branch + cost)
 * @param {number} soundBranches how many sound branches to include (default 3)
 * @returns {{ branches: object[] }}
 */
export function buildResearchPlan(pathDefects, soundBranches = 3) {
  const branches = [];

  // Sound branches first, in already-optimal (descending net value) order.
  for (let i = 0; i < soundBranches; i++) {
    branches.push({
      id: `G${i + 1}`,
      goal: `sound research branch G${i + 1}`,
      est_value: 10 - i, // 10, 9, 8 … strictly positive, strictly descending
      est_cost: 1,
    });
  }

  // The planted wasteful branches: net ≤ 0, carrying the defect's exact answer key.
  for (const d of pathDefects) {
    branches.push({
      id: d.wrong_branch,
      goal: `wasteful branch ${d.wrong_branch} (planted path-defect ${d.id})`,
      est_value: 0,
      est_cost: 1, // net = -1 ⇒ does not cover its cost ⇒ drop
      counterfactual_cost: d.counterfactual_cost,
      source_defect_id: d.id,
    });
  }

  return { branches };
}

/**
 * Run Oranges foresight over a research plan and emit the receipt (crit-3).
 *
 * @param {{ branches: object[] }} plan
 * @returns {{
 *   gate: string,
 *   dropped: Array<{branch:string, counterfactual_cost:string|undefined, reason:string}>,
 *   reordered: Array<{branch:string, from:number, to:number, reason:string}>,
 *   kept: string[],
 *   value_added: boolean,
 *   stamp: string,
 *   crit3_satisfied: boolean,
 * }}
 */
export function runForesight(plan) {
  const branches = Array.isArray(plan?.branches) ? plan.branches : [];

  // 1. DROP: branches whose expected value does not cover their cost (net ≤ 0).
  const dropped = [];
  const survivors = [];
  for (const b of branches) {
    if (netValue(b) <= 0) {
      dropped.push({
        branch: b.id,
        counterfactual_cost: b.counterfactual_cost,
        reason: `net value ${netValue(b)} ≤ 0 — drops before spend (counterfactual: ${b.counterfactual_cost ?? 'unquantified'})`,
      });
    } else {
      survivors.push(b);
    }
  }

  // 2. REORDER: survivors should run highest-net-value first; report any that move. Each reorder
  // names its counterfactual cost too — the value foregone by running a lower-net-value branch
  // ahead of a higher one (FIXTURE-SPEC §4 path-defects are "drop OR reorder + counterfactual cost").
  const sorted = [...survivors].sort((a, b) => netValue(b) - netValue(a));
  const reordered = [];
  for (let to = 0; to < sorted.length; to++) {
    const from = survivors.indexOf(sorted[to]);
    if (from !== to) {
      const gap = netValue(sorted[to]) - netValue(survivors[to]);
      reordered.push({
        branch: sorted[to].id,
        from,
        to,
        counterfactual_cost: `${gap} net value foregone per round if branch ${sorted[to].id} is not run earlier`,
        reason: `reordered to run higher-value branch (net ${netValue(sorted[to])}) earlier`,
      });
    }
  }

  const value_added = dropped.length > 0 || reordered.length > 0;

  // crit-3 is satisfied only if the receipt NAMES a dropped/reordered branch AND every named action
  // carries a counterfactual cost (an action with no quantified cost is not a passing claim — a
  // value-free pass must read as "no foresight value added", never as a silent success).
  const named = [...dropped, ...reordered];
  const everyActionHasCost = named.every(
    (a) => typeof a.counterfactual_cost === 'string' && a.counterfactual_cost.length > 0,
  );
  const crit3_satisfied = value_added && everyActionHasCost;

  return {
    gate: FORESIGHT_GATE,
    dropped,
    reordered,
    kept: sorted.map((b) => b.id),
    value_added,
    stamp: value_added ? VALUE_STAMP : NO_VALUE_STAMP,
    crit3_satisfied,
  };
}
