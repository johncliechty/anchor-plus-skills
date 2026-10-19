// Gandalf advisor — the diagnose-core SEAM (Wave 2).
//
// NS1 UNDERSTAND: Gandalf does NOT re-derive its own diagnosis. It COMPOSES the vetted
// diagnose core (PROTOCOL v2 / the converged `../crucible/MASTER-PLAN.md`). This module is
// the SOLE seam through which a diagnosis earns its `gandalf_core` provenance — the single
// source of truth for "what counts as a vetted-core diagnose finding." The B5 canary
// (test/harness.mjs `assertDiagnoseCoreProvenance`) enforces, at the deterministic gate,
// that every diagnose finding carries this provenance and NO external commission id; a
// finding re-derived inline (or sourced from a commissioned skill) FAILS.
//
// Public surface:
//   GANDALF_CORE_PROTOCOL                     — the vetted diagnose-core protocol marker
//   EXTERNAL_COMMISSION_FIELDS                — commission-id fields forbidden on a diagnosis
//   stampDiagnoseCoreProvenance(finding)      — mark a finding as a vetted-core diagnosis
//   isDiagnoseCoreProvenanced(finding)        — predicate: carries valid gandalf_core provenance

/** The vetted diagnose core's protocol marker. A diagnose finding's `gandalf_core`
 *  provenance must name THIS protocol; any other value (or an absent envelope) reads as
 *  "re-derived inline / foreign source" and FAILS B5. */
export const GANDALF_CORE_PROTOCOL = 'PROTOCOL v2';

/** Commission-id fields that, if populated on a diagnose finding, mean the diagnosis was
 *  sourced from a COMMISSIONED skill rather than the vetted core. Diagnosis is exclusive
 *  to the core, so their presence on a `kind:'diagnose'` finding FAILS B5. (SITUATE
 *  findings legitimately carry researchprime_commission_id — that is a later wave's seam.) */
export const EXTERNAL_COMMISSION_FIELDS = ['researchprime_commission_id', 'crucible_commission_id', 'commission_id'];

/** Stamp a finding as a vetted-core diagnosis: returns a FRESH finding marked
 *  `kind:'diagnose'` and carrying the `gandalf_core` provenance envelope. This is the only
 *  sanctioned way to mint diagnose provenance, which is what makes the vetted core the SOLE
 *  diagnosis source. Existing keys keep their insertion order (so a reasoning-before-verdict
 *  finding stays reasoning-before-verdict); the provenance is appended.
 *  Throws if `finding` is not an object. */
export function stampDiagnoseCoreProvenance(finding) {
  if (finding === null || typeof finding !== 'object' || Array.isArray(finding)) {
    throw new Error('diagnose-core: stampDiagnoseCoreProvenance target is not an object');
  }
  return { ...finding, kind: 'diagnose', gandalf_core: { protocol: GANDALF_CORE_PROTOCOL } };
}

/** Predicate: does `finding` carry valid vetted-core provenance? True iff its `gandalf_core`
 *  envelope names the vetted-core protocol. Used by the B5 canary; pure, never throws. */
export function isDiagnoseCoreProvenanced(finding) {
  if (finding === null || typeof finding !== 'object') return false;
  const prov = finding.gandalf_core;
  if (prov === undefined || prov === null) return false;
  const protocol = typeof prov === 'object' && !Array.isArray(prov) ? prov.protocol : prov;
  return protocol === GANDALF_CORE_PROTOCOL;
}
