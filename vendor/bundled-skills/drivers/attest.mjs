// drivers/attest.mjs — the shared SR-5 served-model attestation stamp.
//
// SR-5: every role stamp records the SERVED model READ FROM THE RESULT ENVELOPE
// (never from argv / the requested model id). If the envelope exposes no served-model
// id, the stamp is DEGRADED (`model_attested:false`, `model_served:null`) — we never
// fabricate a confident model. This single helper is the canonical home of that rule
// so every driver stamps identically (claude.mjs, gemini-cli.mjs, foreman/run-live.mjs).

/** The three fields every SR-5 stamp must carry. */
export const ATTEST_FIELDS = ['model_served', 'model_attested', 'degraded'];

/**
 * Normalize an envelope-read served-model value into the canonical SR-5 triple.
 * @param {?string} served  the model id READ FROM THE ENVELOPE (never argv), or null
 * @returns {{model_served:?string, model_attested:boolean, degraded:boolean}}
 */
export function attestStamp(served) {
  const ok = typeof served === 'string' && served.length > 0;
  return {
    model_served: ok ? served : null,
    model_attested: ok,
    degraded: !ok,
  };
}

/**
 * True iff `rec` carries a well-formed, INTERNALLY-CONSISTENT SR-5 stamp: all three
 * fields present, and `model_attested <=> model_served-present <=> !degraded`. The
 * spawn-site inventory test uses this to assert no driver emits a half-formed or
 * self-contradictory stamp (e.g. attested:true with a null served model).
 * @param {*} rec
 * @returns {boolean}
 */
export function hasAttestation(rec) {
  if (!rec || typeof rec !== 'object') return false;
  for (const f of ATTEST_FIELDS) if (!(f in rec)) return false;
  const attested = rec.model_attested === true;
  const servedPresent = typeof rec.model_served === 'string' && rec.model_served.length > 0;
  return (
    rec.degraded === !attested &&
    attested === servedPresent &&
    (attested || rec.model_served === null)
  );
}
