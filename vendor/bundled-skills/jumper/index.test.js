// Hermeticity pin (P1 2026-07-25): host model prefs (e.g. coding=review=grok in
// ~/.anchor/model_prefs.json) made Gate-3 seating resolve SAME-family, so the
// engine's (correct) JumperSelfReviewHalt failed 9 suite tests on such hosts.
// Pin independent families — env outranks the prefs file — so the suite is
// hermetic everywhere. The engine refusal itself stays covered by the tests
// that pin same-family deliberately.
process.env.CODING_FAMILY = 'claude';
process.env.REVIEW_FAMILY = 'gemini';

import test from 'node:test';
import assert from 'node:assert';
import { Synthesizer, runGandalf, PetersonQuery, petersonQuery, HesseGlassBead, hesseGlassBead, DiracTransfer, diracTransfer, KillFilter, killFilter, Jumper, jumper } from './index.js';


test('Wave 1: Synthesizer exists and can be constructed', () => {
  const synth = new Synthesizer();
  assert.ok(synth);
  assert.ok(Array.isArray(synth.history));
});

test('Wave 1: Synthesizer can receive state updates and calls agent with Parable of the Oranges instructions', async () => {
  let calledPrompt = null;
  let calledSchema = null;
  
  const mockRunAgent = async (opts) => {
    calledPrompt = opts.prompt;
    calledSchema = opts.schema;
    return {
      analysis: 'Synthesized need for a non-volatile ledger to prevent restart loss.',
      steeringFlags: [
        'STEER: Do not just store events in an in-memory Set; identify the durability boundary.',
        'STEER: Look at the structural properties of double-entry bookkeeping for transaction parity.'
      ]
    };
  };

  const synth = new Synthesizer({ runAgent: mockRunAgent });
  const mockState = {
    problem: 'webhook idempotency with no external dependencies',
    currentPhase: 'Peterson Query',
    anomalousData: ['in-process Set is volatile']
  };

  const result = await synth.update(mockState);
  
  // Assert state is pushed to history
  assert.equal(synth.history.length, 1);
  assert.deepEqual(synth.history[0], mockState);
  
  // Assert runAgent was called with prompt containing the Parable of the Oranges context
  assert.ok(calledPrompt.includes('Oranges'));
  assert.ok(calledPrompt.includes('Synthesizer'));
  
  // Assert schema was passed
  assert.deepEqual(calledSchema.required, ['analysis', 'steeringFlags']);
  
  // Assert result matches mock response
  assert.deepEqual(result.steeringFlags, [
    'STEER: Do not just store events in an in-memory Set; identify the durability boundary.',
    'STEER: Look at the structural properties of double-entry bookkeeping for transaction parity.'
  ]);
});

test('Wave 1: runGandalf constructs the prompt and returns a conformant advisor output via applySeamPass', async () => {
  let calledPrompt = null;
  const mockRawDraft = {
    reasoning: 'The dedupe solution relies on Set memory which does not persist across restarts.',
    verdict: 'durable idempotency key required',
    findings: [
      {
        id: 'd-durability',
        kind: 'diagnose',
        rung: 'CLAIMED',
        reasoning: 'Restart drops Set.',
        verdict: 'not durable',
        severity: 'major'
      }
    ],
    nitpicks: [],
    elevations: []
  };

  const mockRunAgent = async (opts) => {
    calledPrompt = opts.prompt;
    return mockRawDraft;
  };

  const result = await runGandalf('idempotency problem', { runAgent: mockRunAgent });
  
  // Verify that it has run through applySeamPass:
  // e.g. finding has gandalf_core appended
  const diag = result.findings.find(f => f.id === 'd-durability');
  assert.ok(diag);
  assert.ok(diag.gandalf_core);
  assert.equal(diag.gandalf_core.protocol, 'PROTOCOL v2');
  
  // Verify it contains other schema-conformant fields
  assert.equal(result.schema_version, 'gandalf-advisor-1');
  assert.equal(result.cross_model, false);
});

test('Wave 2: PetersonQuery deconstructs the problem using SCAMPER and highlights a contradiction', async () => {
  let calledPrompt = null;
  let calledSchema = null;
  
  const mockGandalfRead = {
    reasoning: 'Webhook idempotency key stores are volatile.',
    verdict: 'need persistent deduplication',
    findings: [
      {
        id: 'd-1',
        kind: 'diagnose',
        rung: 'CLAIMED',
        reasoning: 'Memory drops.',
        verdict: 'non-durable storage',
        severity: 'major'
      }
    ],
    nitpicks: [],
    elevations: []
  };

  const mockRunAgent = async (opts) => {
    calledPrompt = opts.prompt;
    calledSchema = opts.schema;
    return {
      anomalousData: ['volatile memory in stateless container environment'],
      scamperAnalysis: {
        substitute: 'Substitute memory storage with a redis instance or disk file.',
        combine: 'Combine the webhook receiver with a light transactional outbox.',
        adapt: 'Adapt standard TCP retry window limits.',
        modify: 'Magnify key uniqueness by adding timestamps.',
        putToOtherUse: 'Use memory-mapped files.',
        eliminate: 'Eliminate local state storage completely.',
        reverse: 'Reverse the client-push to server-pull queue.'
      },
      coreContradictions: [
        {
          description: 'The system must be stateless for horizontal scaling but stateful to ensure webhook idempotency.',
          conflictingDemands: 'Stateless vs Stateful'
        }
      ]
    };
  };

  const query = new PetersonQuery({ runAgent: mockRunAgent });
  const result = await query.run(mockGandalfRead, { steeringFlags: ['STEER: test flag'] });

  // Assert result matches mock response
  assert.ok(result.anomalousData);
  assert.ok(result.scamperAnalysis);
  assert.equal(result.coreContradictions.length, 1);
  assert.equal(result.coreContradictions[0].conflictingDemands, 'Stateless vs Stateful');

  // Verify prompt and schema details
  assert.ok(calledPrompt.includes('SCAMPER'));
  assert.ok(calledPrompt.includes('Peterson Query'));
  assert.ok(calledPrompt.includes('STEER: test flag'));
  assert.deepEqual(calledSchema.required, ['anomalousData', 'scamperAnalysis', 'coreContradictions']);
  assert.deepEqual(calledSchema.properties.scamperAnalysis.required, [
    'substitute', 'combine', 'adapt', 'modify', 'putToOtherUse', 'eliminate', 'reverse'
  ]);
});

test('Wave 2: petersonQuery helper function works identically', async () => {
  const mockGandalfRead = {};
  const mockRunAgent = async (opts) => {
    return {
      anomalousData: [],
      scamperAnalysis: {
        substitute: '', combine: '', adapt: '', modify: '', putToOtherUse: '', eliminate: '', reverse: ''
      },
      coreContradictions: [
        { description: 'conflict', conflictingDemands: 'both' }
      ]
    };
  };

  const result = await petersonQuery(mockGandalfRead, { runAgent: mockRunAgent });
  assert.equal(result.coreContradictions[0].conflictingDemands, 'both');
});

test('Wave 3: HesseGlassBead maps a deconstructed problem map onto a foreign domain', async () => {
  let calledPrompt = null;
  let calledSchema = null;

  const mockProblemMap = {
    anomalousData: ['volatile memory in stateless container environment'],
    scamperAnalysis: {
      substitute: 'Substitute memory storage with a redis instance or disk file.',
      combine: 'Combine the webhook receiver with a light transactional outbox.',
      adapt: 'Adapt standard TCP retry window limits.',
      modify: 'Magnify key uniqueness by adding timestamps.',
      putToOtherUse: 'Use memory-mapped files.',
      eliminate: 'Eliminate local state storage completely.',
      reverse: 'Reverse the client-push to server-pull queue.'
    },
    coreContradictions: [
      {
        description: 'The system must be stateless for horizontal scaling but stateful to ensure webhook idempotency.',
        conflictingDemands: 'Stateless vs Stateful'
      }
    ]
  };

  const mockRunAgent = async (opts) => {
    calledPrompt = opts.prompt;
    calledSchema = opts.schema;
    return {
      foreignDomain: 'Cellular membrane transport proteins',
      analogyReasoning: 'Membranes regulate inflow/outflow via active/passive gates without losing cellular integrity.',
      structuralMapping: [
        {
          originalElement: 'Webhook payload deduplication key',
          foreignElement: 'Receptor binding site configuration',
          mappingRationale: 'Ensures only specific matching items trigger the pathway.'
        }
      ],
      mappedContradictions: [
        {
          originalContradiction: 'The system must be stateless for horizontal scaling but stateful to ensure webhook idempotency.',
          foreignContradiction: 'The cell wall must be selectively permeable to maintain homeostasis while dynamically adjusting to osmotic pressure.',
          structuralParallel: 'Permeability vs Homeostatic stability'
        }
      ]
    };
  };

  const bead = new HesseGlassBead({ runAgent: mockRunAgent });
  const result = await bead.run(mockProblemMap, { steeringFlags: ['STEER: focus on biological cell membrane'] });

  // Assert result matches mock response
  assert.equal(result.foreignDomain, 'Cellular membrane transport proteins');
  assert.equal(result.structuralMapping[0].originalElement, 'Webhook payload deduplication key');
  assert.equal(result.mappedContradictions[0].structuralParallel, 'Permeability vs Homeostatic stability');

  // Verify prompt and schema details
  assert.ok(calledPrompt.includes('Hesse Glass Bead'));
  assert.ok(calledPrompt.includes('foreignDomain'));
  assert.ok(calledPrompt.includes('STEER: focus on biological cell membrane'));
  assert.deepEqual(calledSchema.required, ['foreignDomain', 'analogyReasoning', 'structuralMapping', 'mappedContradictions']);
});

test('Wave 3: hesseGlassBead helper function works identically', async () => {
  const mockProblemMap = {};
  const mockRunAgent = async (opts) => {
    return {
      foreignDomain: 'Renaissance Fresco Painting',
      analogyReasoning: '',
      structuralMapping: [],
      mappedContradictions: []
    };
  };

  const result = await hesseGlassBead(mockProblemMap, { runAgent: mockRunAgent });
  assert.equal(result.foreignDomain, 'Renaissance Fresco Painting');
});

test('Wave 4: DiracTransfer resolves contradictions using TRIZ and maps back to original domain', async () => {
  let calledPrompt = null;
  let calledSchema = null;
  let calledDriver = null;

  const mockAnalogicalMapping = {
    foreignDomain: 'Cellular membrane transport proteins',
    analogyReasoning: 'Membranes regulate inflow/outflow via active/passive gates without losing cellular integrity.',
    structuralMapping: [
      {
        originalElement: 'Webhook payload deduplication key',
        foreignElement: 'Receptor binding site configuration',
        mappingRationale: 'Ensures only specific matching items trigger the pathway.'
      }
    ],
    mappedContradictions: [
      {
        originalContradiction: 'The system must be stateless for horizontal scaling but stateful to ensure webhook idempotency.',
        foreignContradiction: 'The cell wall must be selectively permeable to maintain homeostasis while dynamically adjusting to osmotic pressure.',
        structuralParallel: 'Permeability vs Homeostatic stability'
      }
    ]
  };

  const mockCoreContradictions = [
    {
      description: 'The system must be stateless for horizontal scaling but stateful to ensure webhook idempotency.',
      conflictingDemands: 'Stateless vs Stateful'
    }
  ];

  const mockRunAgent = async (opts) => {
    calledPrompt = opts.prompt;
    calledSchema = opts.schema;
    calledDriver = opts.driver;
    return {
      trizPrinciplesApplied: ['Segmentation', 'Feedback'],
      analogicalResolution: 'Introduce local receptor channels that dynamically bind keys with transient memory states.',
      symmetricalResolution: 'Store deduplication keys in a distributed, memory-mapped cache with active eviction rules.',
      resolutionReasoning: 'Resolves statelessness vs statefulness by separating routing from the transient deduplication state.'
    };
  };

  const transfer = new DiracTransfer({ runAgent: mockRunAgent, driver: 'instance-driver' });
  const result = await transfer.run(mockAnalogicalMapping, mockCoreContradictions, {
    steeringFlags: ['STEER: focus on cache eviction'],
    driver: 'override-driver'
  });

  // Assert result matches mock response
  assert.deepEqual(result.trizPrinciplesApplied, ['Segmentation', 'Feedback']);
  assert.equal(result.symmetricalResolution, 'Store deduplication keys in a distributed, memory-mapped cache with active eviction rules.');

  // Verify prompt, schema, and driver details
  assert.ok(calledPrompt.includes('Dirac Transfer'));
  assert.ok(calledPrompt.includes('trizPrinciplesApplied'));
  assert.ok(calledPrompt.includes('STEER: focus on cache eviction'));
  assert.deepEqual(calledSchema.required, ['trizPrinciplesApplied', 'analogicalResolution', 'symmetricalResolution', 'resolutionReasoning']);
  assert.equal(calledDriver, 'override-driver');
});

test('Wave 4: diracTransfer helper function works identically with two arguments', async () => {
  const mockAnalogicalMapping = {};
  const mockRunAgent = async (opts) => {
    return {
      trizPrinciplesApplied: ['Asymmetry'],
      analogicalResolution: '',
      symmetricalResolution: 'Resolved',
      resolutionReasoning: ''
    };
  };

  const result = await diracTransfer(mockAnalogicalMapping, { runAgent: mockRunAgent });
  assert.equal(result.symmetricalResolution, 'Resolved');
});

test('DiracTransfer: does not discard options when the second parameter is an options object', async () => {
  let calledDriver = null;
  const mockAnalogicalMapping = {};
  const mockRunAgent = async (opts) => {
    calledDriver = opts.driver;
    return {
      trizPrinciplesApplied: ['Asymmetry'],
      analogicalResolution: '',
      symmetricalResolution: 'Resolved',
      resolutionReasoning: ''
    };
  };

  await diracTransfer(mockAnalogicalMapping, { runAgent: mockRunAgent }, { driver: 'correct-driver' });
  assert.equal(calledDriver, 'correct-driver');
});

test('Wave 5: KillFilter exists and can be constructed', () => {
  const filter = new KillFilter();
  assert.ok(filter);
});

test('Wave 5: KillFilter passes when all three gates return passed=true', async () => {
  let callCount = 0;
  const mockRunAgent = async (opts) => {
    callCount++;
    if (opts.label === 'KillFilterGate1and2') {
      return {
        gate1: { passed: true, reasoning: 'Gate 1 passed successfully.' },
        gate2: { passed: true, reasoning: 'Gate 2 passed successfully.' }
      };
    }
    return {
      passed: true,
      reasoning: `Gate ${callCount} passed successfully.`
    };
  };

  const filter = new KillFilter({ runAgent: mockRunAgent });
  const mockConcept = {
    symmetricalResolution: 'A sound database synchronization system',
    resolutionReasoning: 'Uses standard raft consensus',
    analogicalMapping: {
      foreignDomain: 'Water distribution systems',
      analogyReasoning: 'Flow control maps to rate limits'
    },
    coreContradictions: []
  };

  const result = await filter.run(mockConcept);
  assert.equal(result.passed, true);
  assert.equal(result.failedAtGate, null);
  assert.equal(result.rejectionReason, null);
  assert.equal(result.gateLogs.length, 3);
  assert.equal(result.gateLogs[0].passed, true);
  assert.equal(result.gateLogs[1].passed, true);
  assert.equal(result.gateLogs[2].passed, true);
  assert.equal(callCount, 2); // one merged gates-1+2 call + one Gate 3 call
});

test('Wave 5: KillFilter rejects at Gate 1 and short-circuits', async () => {
  let callCount = 0;
  const mockRunAgent = async (opts) => {
    callCount++;
    return {
      gate1: { passed: false, reasoning: 'Violates perpetual motion laws.' },
      gate2: { passed: true, reasoning: 'irrelevant — mapping missing makes gate 2 deterministic anyway' }
    };
  };

  const filter = new KillFilter({ runAgent: mockRunAgent });
  const mockConcept = {
    symmetricalResolution: 'Perpetual energy device',
    resolutionReasoning: 'Uses gravity loops'
  };

  const result = await filter.run(mockConcept);
  assert.equal(result.passed, false);
  assert.equal(result.failedAtGate, 1);
  assert.equal(result.rejectionReason, 'Violates perpetual motion laws.');
  assert.equal(result.gateLogs.length, 1);
  assert.equal(callCount, 1); // only the merged gates-1+2 call; Gate 3 is not evaluated
});

test('Wave 5: KillFilter rejects at Gate 2 and short-circuits', async () => {
  let callCount = 0;
  const mockRunAgent = async (opts) => {
    callCount++;
    return {
      gate1: { passed: true, reasoning: 'Concept is theoretically possible.' },
      gate2: { passed: false, reasoning: 'Analogy has no structural integrity.' }
    };
  };

  const filter = new KillFilter({ runAgent: mockRunAgent });
  const mockConcept = {
    symmetricalResolution: 'Database sync',
    resolutionReasoning: 'Standard raft consensus',
    analogicalMapping: {
      foreignDomain: 'Noodles',
      analogyReasoning: 'Noodle shape maps to consensus'
    }
  };

  const result = await filter.run(mockConcept);
  assert.equal(result.passed, false);
  assert.equal(result.failedAtGate, 2);
  assert.equal(result.rejectionReason, 'Analogy has no structural integrity.');
  assert.equal(result.gateLogs.length, 2);
  assert.equal(callCount, 1); // gates 1+2 are one merged call; Gate 3 is not evaluated
});

test('Wave 5: KillFilter rejects at Gate 3 (Adversarial Gate)', async () => {
  let callCount = 0;
  const mockRunAgent = async (opts) => {
    callCount++;
    if (opts.label === 'KillFilterGate1and2') {
      return {
        gate1: { passed: true, reasoning: 'Concept is theoretically possible.' },
        gate2: { passed: true, reasoning: 'Analogy is structurally valid.' }
      };
    }
    return { passed: false, reasoning: 'Adversarial scan found logic gap: no backup system.' };
  };

  const filter = new KillFilter({ runAgent: mockRunAgent });
  const mockConcept = {
    symmetricalResolution: 'Database sync',
    resolutionReasoning: 'Standard raft consensus',
    analogicalMapping: {
      foreignDomain: 'Water distribution systems',
      analogyReasoning: 'Flow control maps to rate limits'
    }
  };

  const result = await filter.run(mockConcept);
  assert.equal(result.passed, false);
  assert.equal(result.failedAtGate, 3);
  assert.equal(result.rejectionReason, 'Adversarial scan found logic gap: no backup system.');
  assert.equal(result.gateLogs.length, 3);
  assert.equal(callCount, 2); // one merged gates-1+2 call + one Gate 3 call
});

test('Wave 5: killFilter helper function works identically', async () => {
  const mockConcept = {
    symmetricalResolution: 'Res',
    resolutionReasoning: 'Reason',
    analogicalMapping: {
      foreignDomain: 'Water distribution systems',
      analogyReasoning: 'Flow control maps to rate limits'
    }
  };
  const mockRunAgent = async (opts) => {
    if (opts.label === 'KillFilterGate1and2') {
      return {
        gate1: { passed: true, reasoning: 'OK' },
        gate2: { passed: true, reasoning: 'OK' }
      };
    }
    return { passed: true, reasoning: 'OK' };
  };

  const result = await killFilter(mockConcept, { runAgent: mockRunAgent });
  assert.equal(result.passed, true);
  assert.equal(result.gateLogs[0].passed, true);
});

test('Wave 6: Jumper class can run end-to-end pipeline and outputs Grounding Execution Protocol on success', async () => {
  let callCount = 0;
  const mockRunAgent = async (opts) => {
    callCount++;
    if (opts.label === 'GandalfDraft') {
      return { reasoning: 'gandalf reasoning', verdict: 'gandalf verdict', findings: [], nitpicks: [], elevations: [] };
    }
    if (opts.label === 'Synthesizer') {
      return { analysis: 'synth analysis', steeringFlags: ['STEER: flag'] };
    }
    if (opts.label === 'PetersonQuery') {
      return {
        anomalousData: ['anomaly'],
        scamperAnalysis: { substitute: '', combine: '', adapt: '', modify: '', putToOtherUse: '', eliminate: '', reverse: '' },
        coreContradictions: [{ description: 'contradiction', conflictingDemands: 'demands' }]
      };
    }
    if (opts.label === 'HesseGlassBead') {
      return {
        foreignDomain: 'foreign domain',
        analogyReasoning: 'analogy reasoning',
        structuralMapping: [],
        mappedContradictions: []
      };
    }
    if (opts.label === 'DiracTransfer') {
      return {
        trizPrinciplesApplied: ['Segmentation'],
        analogicalResolution: 'analogical res',
        symmetricalResolution: 'symmetrical res',
        resolutionReasoning: 'resolution reasoning'
      };
    }
    if (opts.label === 'KillFilterGate1and2') {
      return {
        gate1: { passed: true, reasoning: 'gate passed' },
        gate2: { passed: true, reasoning: 'gate passed' }
      };
    }
    if (opts.label === 'KillFilterGate3') {
      return { passed: true, reasoning: 'gate passed' };
    }
    if (opts.label === 'GroundingExecutionProtocol') {
      return {
        domainType: 'software',
        validationSetup: 'setup detail',
        concreteSteps: [{ stepNumber: 1, description: 'step 1', verificationMethod: 'verify 1' }],
        successMetrics: ['metric 1'],
        risksAndMitigations: ['risk 1']
      };
    }
    throw new Error(`Unexpected agent call label: ${opts.label}`);
  };

  const engine = new Jumper({ runAgent: mockRunAgent });
  const result = await engine.run('webhook problem', { fanOut: 1 }); // legacy single-candidate path

  assert.equal(result.passed, true);
  assert.equal(result.concept.symmetricalResolution, 'symmetrical res');
  assert.equal(result.concept.analogicalMapping.foreignDomain, 'foreign domain');
  assert.equal(result.groundingExecutionProtocol.domainType, 'software');
  assert.equal(result.groundingExecutionProtocol.concreteSteps[0].description, 'step 1');
  assert.equal(result.gateLogs.length, 3);
  assert.ok(result.gateLogs.every(g => g.passed === true));
});

test('Wave 6: Jumper class returns failed state if KillFilter rejects concept', async () => {
  const mockRunAgent = async (opts) => {
    if (opts.label === 'GandalfDraft') {
      return { reasoning: 'gandalf reasoning', verdict: 'gandalf verdict', findings: [], nitpicks: [], elevations: [] };
    }
    if (opts.label === 'Synthesizer') {
      return { analysis: 'synth analysis', steeringFlags: ['STEER: flag'] };
    }
    if (opts.label === 'PetersonQuery') {
      return {
        anomalousData: ['anomaly'],
        scamperAnalysis: { substitute: '', combine: '', adapt: '', modify: '', putToOtherUse: '', eliminate: '', reverse: '' },
        coreContradictions: [{ description: 'contradiction', conflictingDemands: 'demands' }]
      };
    }
    if (opts.label === 'HesseGlassBead') {
      return {
        foreignDomain: 'foreign domain',
        analogyReasoning: 'analogy reasoning',
        structuralMapping: [],
        mappedContradictions: []
      };
    }
    if (opts.label === 'DiracTransfer') {
      return {
        trizPrinciplesApplied: ['Segmentation'],
        analogicalResolution: 'analogical res',
        symmetricalResolution: 'symmetrical res',
        resolutionReasoning: 'resolution reasoning'
      };
    }
    if (opts.label === 'KillFilterGate1and2') {
      return {
        gate1: { passed: false, reasoning: 'failed existence proof' },
        gate2: { passed: true, reasoning: 'not reached — gate 1 already failed' }
      };
    }
    throw new Error(`Unexpected agent call label: ${opts.label}`);
  };

  const engine = new Jumper({ runAgent: mockRunAgent });
  const result = await engine.run('webhook problem', { fanOut: 1 }); // legacy single-candidate path

  assert.equal(result.passed, false);
  assert.equal(result.failedAtGate, 1);
  assert.equal(result.rejectionReason, 'failed existence proof');
  assert.equal(result.gateLogs.length, 1);
  assert.equal(result.gateLogs[0].passed, false);
  assert.equal(result.groundingExecutionProtocol, undefined);
});

test('Wave 6: jumper helper function works identically', async () => {
  const mockRunAgent = async (opts) => {
    if (opts.label === 'GandalfDraft') {
      return { reasoning: 'g', verdict: 'v', findings: [], nitpicks: [], elevations: [] };
    }
    if (opts.label === 'Synthesizer') {
      return { analysis: 's', steeringFlags: [] };
    }
    if (opts.label === 'PetersonQuery') {
      return {
        anomalousData: [],
        scamperAnalysis: { substitute: '', combine: '', adapt: '', modify: '', putToOtherUse: '', eliminate: '', reverse: '' },
        coreContradictions: []
      };
    }
    if (opts.label === 'HesseGlassBead') {
      return {
        foreignDomain: 'f',
        analogyReasoning: 'a',
        structuralMapping: [],
        mappedContradictions: []
      };
    }
    if (opts.label === 'DiracTransfer') {
      return {
        trizPrinciplesApplied: [],
        analogicalResolution: '',
        symmetricalResolution: 'ok',
        resolutionReasoning: ''
      };
    }
    if (opts.label === 'KillFilterGate1and2') {
      return {
        gate1: { passed: true, reasoning: 'ok' },
        gate2: { passed: true, reasoning: 'ok' }
      };
    }
    if (opts.label === 'KillFilterGate3') {
      return { passed: true, reasoning: 'ok' };
    }
    if (opts.label === 'GroundingExecutionProtocol') {
      return {
        domainType: 'software',
        validationSetup: '',
        concreteSteps: [],
        successMetrics: [],
        risksAndMitigations: []
      };
    }
    return {};
  };

  const result = await jumper('webhook problem', { runAgent: mockRunAgent, fanOut: 1 }); // legacy path
  assert.equal(result.passed, true);
  assert.equal(result.concept.symmetricalResolution, 'ok');
});



