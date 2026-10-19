// W10 / P7 — Classifier health fields: abstain-rate + unsupervised-spend true-positive.
//
// Surfaces on /api/state and classifyAll so operators can see whether the
// sentinel is flying blind (high abstain) or still catching the orphan TP shape.

/**
 * Compute per-sweep classifier health metrics from engine rows.
 * @param {object[]} engines
 * @returns {object}
 */
function computeClassifierHealthMetrics(engines) {
  const list = Array.isArray(engines) ? engines : [];
  const n = list.length;
  let abstainCount = 0;
  let keepCount = 0;
  let wouldBeActionableRedCount = 0;
  let unsupervisedSpendTpCount = 0;
  let ownedKeepCount = 0;
  let uncertainLegCount = 0;

  for (const e of list) {
    const verdict = e.quadVerdict
      || (e.quad && e.quad.verdict)
      || null;
    const abstain = verdict === 'ABSTAIN'
      || !!(e.quad && e.quad.abstain)
      || (Array.isArray(e.reasonCodes) && e.reasonCodes.includes('VERDICT_ABSTAIN'));
    const keep = verdict === 'KEEP'
      || !!(e.quad && e.quad.keep)
      || !!(e.ownership && (e.ownership.owned || e.ownership.keep || e.ownership.failClosed));
    const wouldBe = e.wouldBeActionableRed === true
      || verdict === 'WOULD_BE_RED'
      || !!(e.quad && e.quad.wouldBeActionableRed);

    if (abstain) abstainCount += 1;
    if (keep) keepCount += 1;
    if (wouldBe) wouldBeActionableRedCount += 1;

    if (e.ownership && (e.ownership.owned || e.ownership.keep || e.ownership.failClosed)) {
      ownedKeepCount += 1;
    }

    const uncertainLegs = (e.quad && e.quad.uncertainLegs) || e.uncertainLegs || [];
    if (Array.isArray(uncertainLegs) && uncertainLegs.length > 0) {
      uncertainLegCount += 1;
    }

    // Unsupervised-spend true-positive shape (OL1 / G3): joint would-be RED on
    // unsupervised paid-spend path — observe dual-run signal, not scare chrome.
    const unsupervised = e.unsupervised === true
      || e.supervisionStatus === 'UNSUPERVISED';
    const spendPos = e.spendPositive === true
      || e.spendingNow === true
      || e.spendStatus === 'SPEND_POSITIVE';
    if (wouldBe && unsupervised && spendPos) {
      unsupervisedSpendTpCount += 1;
    }
  }

  const abstainRate = n > 0 ? abstainCount / n : 0;
  const unsupervisedSpendTpRate = n > 0 ? unsupervisedSpendTpCount / n : 0;

  return {
    engineCount: n,
    abstainCount,
    abstainRate,
    keepCount,
    wouldBeActionableRedCount,
    unsupervisedSpendTruePositiveCount: unsupervisedSpendTpCount,
    unsupervisedSpendTpCount,
    unsupervisedSpendTpRate,
    ownedKeepCount,
    uncertainLegCount,
    // Friendly aliases used by dashboard / Doctor health chips
    health: {
      abstainRate,
      unsupervisedSpendTp: unsupervisedSpendTpCount,
      unsupervisedSpendTruePositive: unsupervisedSpendTpCount,
    },
    version: 'w10-health-metrics-v1',
  };
}

/**
 * Public payload slice for server /api/state.
 * @param {object[]} engines
 * @param {object} [extra]
 */
function getHealthMetricsPublicPayload(engines, extra = {}) {
  const m = computeClassifierHealthMetrics(engines);
  return {
    ...m,
    classifierMode: extra.classifierMode || null,
    atlasHealth: extra.atlasHealth || null,
    sweepError: extra.sweepError != null ? extra.sweepError : null,
  };
}

module.exports = {
  computeClassifierHealthMetrics,
  getHealthMetricsPublicPayload,
};
