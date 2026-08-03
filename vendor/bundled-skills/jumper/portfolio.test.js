// portfolio.test.js — 2026-07 portfolio mode: fan-out tournament, ranked
// survivors + kill log, bounded retry-on-kill, and the portfolio (fanOut 3)
// being the DEFAULT (explicit fanOut:1 selects the legacy single-candidate
// pipeline). Mock-driven exactly like index.test.js (label-keyed).

// Hermeticity pin (P1 2026-07-25): host model prefs (e.g. coding=review=grok in
// ~/.anchor/model_prefs.json) made Gate-3 seating resolve SAME-family, so the
// engine's (correct) JumperSelfReviewHalt failed 9 suite tests on such hosts.
// Pin independent families — env outranks the prefs file — so the suite is
// hermetic everywhere. The engine refusal itself stays covered by the tests
// that pin same-family deliberately.
process.env.CODING_FAMILY = 'claude';
process.env.REVIEW_FAMILY = 'gemini';

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Jumper } from './index.js';

const RAW_DRAFT = {
  reasoning: 'r', verdict: 'v', findings: [], nitpicks: [],
  elevations: [],
};

function makeMock({ gate1PassFrom = 0 } = {}) {
  // gate1PassFrom: the index (0-based) of the first merged KillFilterGate1and2
  // call whose gate1 passes — earlier ones fail (drives the retry-on-kill scenario).
  const counts = {};
  const mock = async (opts) => {
    const label = opts.label;
    counts[label] = (counts[label] || 0) + 1;
    switch (label) {
      case 'GandalfDraft': return { ...RAW_DRAFT };
      case 'Synthesizer': return { analysis: 'a', steeringFlags: [`flag-${counts[label]}`] };
      case 'PetersonQuery': return {
        anomalousData: ['x'],
        scamperAnalysis: { substitute: 's', combine: 'c', adapt: 'a', modify: 'm', putToOtherUse: 'p', eliminate: 'e', reverse: 'r' },
        coreContradictions: [{ description: 'd', conflictingDemands: 'cd' }],
      };
      case 'HesseGlassBead': return {
        foreignDomain: `domain-${counts[label]}`,
        analogyReasoning: 'ar',
        structuralMapping: Array.from({ length: counts[label] }, (_, i) => ({
          originalElement: `o${i}`, foreignElement: `f${i}`, mappingRationale: 'mr',
        })),
        mappedContradictions: [{ originalContradiction: 'oc', foreignContradiction: 'fc', structuralParallel: 'sp' }],
      };
      case 'DiracTransfer': return {
        trizPrinciplesApplied: ['Segmentation'],
        analogicalResolution: 'ares',
        symmetricalResolution: `sres-${counts[label]}`,
        resolutionReasoning: 'rr',
      };
      case 'KillFilterGate1and2': {
        const idx = counts[label] - 1;
        return {
          gate1: idx >= gate1PassFrom
            ? { passed: true, reasoning: 'viable' }
            : { passed: false, reasoning: 'violates axioms (scripted kill)' },
          gate2: { passed: true, reasoning: 'sound analogy' },
        };
      }
      case 'KillFilterGate3': return { passed: true, reasoning: 'symmetric' };
      case 'GroundingExecutionProtocol': return {
        domainType: 'software', validationSetup: 'vs',
        concreteSteps: [{ stepNumber: 1, description: 'd', verificationMethod: 'v' }],
        successMetrics: ['m'], risksAndMitigations: ['r'],
      };
      default: throw new Error(`Unexpected label: ${label}`);
    }
  };
  mock.counts = counts;
  return mock;
}

test('portfolio mode: fanOut=3 runs a tournament and returns ranked survivors + GEP on the top one', async () => {
  const mock = makeMock();
  const engine = new Jumper({ runAgent: mock });
  const result = await engine.run('problem', { fanOut: 3 });

  assert.equal(result.passed, true);
  assert.equal(result.fanOut, 3);
  assert.equal(mock.counts.HesseGlassBead, 3, 'three analogical mappings generated');
  assert.equal(mock.counts.DiracTransfer, 3, 'one resolution per mapping');
  assert.equal(mock.counts.KillFilterGate1and2, 3, 'every candidate judged');
  assert.equal(result.survivors.length, 3);
  // Ranked by structural-mapping richness: the 3rd hesse call had the most.
  assert.equal(result.survivors[0].foreignDomain, 'domain-3');
  assert.deepEqual(result.concept, result.survivors[0].concept, 'GEP attaches to the top survivor');
  assert.ok(result.groundingExecutionProtocol.concreteSteps.length >= 1);
  assert.deepEqual(result.killLog, []);
});

test('portfolio mode: total kill + retryOnKill retries EXACTLY once with the rejections as steering', async () => {
  // First 2 gate-1 calls fail (fanOut=2 → whole first tournament dies), later pass.
  const mock = makeMock({ gate1PassFrom: 2 });
  const engine = new Jumper({ runAgent: mock });
  const result = await engine.run('problem', { fanOut: 2, retryOnKill: true });

  assert.equal(result.passed, true);
  assert.equal(result.retried, true);
  assert.equal(mock.counts.HesseGlassBead, 4, 'two tournaments of two');
  assert.equal(result.survivors.length, 2);
});

test('portfolio mode: total kill WITHOUT retryOnKill returns the kill log honestly', async () => {
  const mock = makeMock({ gate1PassFrom: 99 });
  const engine = new Jumper({ runAgent: mock });
  const result = await engine.run('problem', { fanOut: 2 });

  assert.equal(result.passed, false);
  assert.equal(result.retried, false);
  assert.equal(result.survivors.length, 0);
  assert.equal(result.killLog.length, 2);
  assert.equal(result.killLog[0].failedAtGate, 1);
  assert.match(result.killLog[0].rejectionReason, /scripted kill/);
});

test('default is now the PORTFOLIO (fanOut 3); explicit fanOut:1 selects the legacy pipeline', async () => {
  // No fanOut option ⇒ portfolio mode with fanOut 3.
  const mock = makeMock();
  const engine = new Jumper({ runAgent: mock });
  const result = await engine.run('problem', {});

  assert.equal(result.passed, true);
  assert.equal(result.fanOut, 3, 'the default is a 3-candidate portfolio');
  assert.ok(Array.isArray(result.survivors), 'portfolio shape carries survivors');
  assert.equal(mock.counts.HesseGlassBead, 3);

  // Explicit fanOut:1 ⇒ the legacy single-candidate pipeline (no portfolio fields).
  const legacyMock = makeMock();
  const legacyEngine = new Jumper({ runAgent: legacyMock });
  const legacyResult = await legacyEngine.run('problem', { fanOut: 1 });

  assert.equal(legacyResult.passed, true);
  assert.ok(!('fanOut' in legacyResult), 'legacy shape carries no portfolio fields');
  assert.equal(legacyResult.survivors, undefined);
  assert.equal(legacyMock.counts.HesseGlassBead, 1);
  assert.ok(legacyResult.groundingExecutionProtocol);
});
