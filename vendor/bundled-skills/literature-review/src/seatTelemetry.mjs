// Receipt-derived seat telemetry for literature-review run records.
// Family/model truth comes from Trio's final trio.seat.v1 receipt, never from
// the configured route or a hard-coded historical split.

function clean(value, max = 240) {
  const text = typeof value === 'string' ? value.trim() : '';
  return text ? text.slice(0, max) : null;
}

function compactReceipt(receipt) {
  if (!receipt || typeof receipt !== 'object') return null;
  const served = receipt.served && typeof receipt.served === 'object'
    ? receipt.served
    : null;
  const requested = receipt.requested && typeof receipt.requested === 'object'
    ? receipt.requested
    : null;
  return {
    schema: receipt.schema ?? null,
    ok: receipt.ok === true,
    status: clean(receipt.status),
    label: clean(receipt.label),
    role: clean(receipt.role),
    verification: receipt.verification === true,
    requested: requested ? {
      driver: clean(requested.driver),
      family: clean(requested.family),
      model: clean(requested.model),
    } : null,
    served: served ? {
      driver: clean(served.driver),
      family: clean(served.family),
      model: clean(served.model),
      family_attested: served.family_attested === true,
      model_attested: served.model_attested === true,
    } : null,
    failover_used: receipt.failover?.used === true,
  };
}

export function makeSeatTelemetry() {
  const entries = [];
  const seen = new WeakSet();
  return {
    note(receipt) {
      if (!receipt || typeof receipt !== 'object') return false;
      if (seen.has(receipt)) return true;
      seen.add(receipt);
      const compact = compactReceipt(receipt);
      if (!compact) return false;
      entries.push(compact);
      return true;
    },
    receiptForLabel(label) {
      const wanted = clean(label);
      return [...entries].reverse().find((entry) => entry.ok && entry.label === wanted) ?? null;
    },
    families() {
      // A failover-substituted serve (coding seat fell over to another family) is a
      // real call but NOT evidence of cross-family review — counting it inflates
      // cross_model on a run whose verification stayed single-family. Verification
      // roles cannot fail over (trio blocks it), so this only excludes coding-seat
      // substitutions. Conservative by design: understate, never overstate.
      return [...new Set(entries
        .filter((entry) => entry.ok && entry.served?.family_attested && entry.served.family
          && !entry.failover_used)
        .map((entry) => entry.served.family.toLowerCase()))].sort();
    },
    models() {
      const grouped = new Map();
      for (const entry of entries) {
        if (!entry.ok || !entry.served?.family_attested || !entry.served.family
          || entry.failover_used) continue;
        const value = {
          family: entry.served.family.toLowerCase(),
          driver: entry.served.driver,
          model: entry.served.model_attested ? entry.served.model : null,
          model_attested: entry.served.model_attested,
          calls: 0,
        };
        const key = JSON.stringify([value.family, value.driver, value.model, value.model_attested]);
        const prior = grouped.get(key) ?? value;
        prior.calls += 1;
        grouped.set(key, prior);
      }
      return [...grouped.values()];
    },
    entries() { return entries.map((entry) => structuredClone(entry)); },
  };
}

export function wrapAgentWithSeatTelemetry(agent, telemetry) {
  if (typeof agent !== 'function') throw new TypeError('wrapAgentWithSeatTelemetry requires agent()');
  if (!telemetry || typeof telemetry.note !== 'function') {
    throw new TypeError('wrapAgentWithSeatTelemetry requires makeSeatTelemetry()');
  }
  return async (prompt, opts = {}) => {
    const callerReceipt = opts.onReceipt;
    try {
      return await agent(prompt, {
        ...opts,
        onReceipt: async (receipt) => {
          telemetry.note(receipt);
          if (typeof callerReceipt === 'function') await callerReceipt(receipt);
        },
      });
    } catch (error) {
      if (error?.receipt) telemetry.note(error.receipt);
      throw error;
    }
  };
}

export function seatRecordFields(telemetry) {
  const families = telemetry?.families?.() ?? [];
  const models = telemetry?.models?.() ?? [];
  return {
    cross_model: families.length > 1,
    seat_families: families,
    models,
    tier: models.length === 0
      ? 'deterministic-only'
      : families.length > 1
        ? 'live-cross-family'
        : 'live-single-family',
  };
}

export default { makeSeatTelemetry, wrapAgentWithSeatTelemetry, seatRecordFields };
