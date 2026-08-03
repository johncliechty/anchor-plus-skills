// bin/two-gate.mjs
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { HaltError } from './trio-core/contract-core.mjs';
import { runIntake } from './intake.mjs';
import { planMatrix } from './matrix-planner.mjs';
import { validate, CURRENT_SCHEMA_VERSION } from './governance.mjs';
import { ApprovalProvider } from './approval-provider.mjs';

const MAX_EDITS = 3;

/**
 * Validates the state machine preconditions to reach execution.
 * Both gate records must exist, hashes must match the actual artifacts, and decisions must be APPROVE.
 * @param {string} runDir
 * @param {string} triageHash 
 * @param {string} planHash 
 */
export function validateExecutionState(runDir, triageHash, planHash) {
  const gate1Path = path.join(runDir, 'gate1-record.json');
  const gate2Path = path.join(runDir, 'gate2-record.json');

  if (!fs.existsSync(gate1Path)) throw new HaltError('Execution blocked: Gate 1 record missing');
  if (!fs.existsSync(gate2Path)) throw new HaltError('Execution blocked: Gate 2 record missing');

  const gate1 = JSON.parse(fs.readFileSync(gate1Path, 'utf8'));
  const gate2 = JSON.parse(fs.readFileSync(gate2Path, 'utf8'));

  if (gate1.triageHash !== triageHash) {
    throw new HaltError('Execution blocked: Gate 1 approval not bound to current triage artifact hash');
  }
  if (gate2.planHash !== planHash) {
    throw new HaltError('Execution blocked: Gate 2 approval not bound to current plan artifact hash');
  }

  if (gate1.gate1Decision !== 'APPROVE') {
    throw new HaltError(`Execution blocked: Gate 1 decision is ${gate1.gate1Decision}, expected APPROVE`);
  }
  if (gate2.gate2Decision !== 'APPROVE') {
    throw new HaltError(`Execution blocked: Gate 2 decision is ${gate2.gate2Decision}, expected APPROVE`);
  }
  
  return true;
}

/**
 * Runs the two-gate process.
 */
export async function runTwoGateMachine(inputs, { runDir, promptGate1, promptGate2, maxEdits = MAX_EDITS, lockedGovernorOutput = { hash: 'mock-hash' }, skill = 'researchPrime', onEditedScope, onEditedPlan, approvalProvider, buildPlan } = {}) {
  let providerIdentity = 'TTY';
  if (approvalProvider) {
    providerIdentity = approvalProvider.authorize();
  }

  // If non-interactive provider, auto-approve
  if (providerIdentity !== 'TTY') {
    promptGate1 = async () => 'APPROVE';
    promptGate2 = async () => 'APPROVE';
  }

  try {
    let triageResult;
    let gate1Edits = 0;
    
    // GATE 1
    while (true) {
      triageResult = await runIntake(inputs, { runDir, promptHuman: promptGate1 });
      if (triageResult.decision === 'APPROVE') {
        break;
      } else if (triageResult.decision === 'EDIT') {
        gate1Edits++;
        if (gate1Edits > maxEdits) throw new HaltError(`Run halted at Gate 1: exceeded max EDIT cycles (${maxEdits})`);
        if (onEditedScope) inputs = await onEditedScope(inputs);
        continue;
      } else {
        // Should not be reached because runIntake throws on ABORT, but added for safety
        throw new HaltError(`Run halted at Gate 1 with decision ${triageResult.decision}`);
      }
    }

    // GATE 2
    let gate2Edits = 0;
    let planHash;
    let gate2Decision;
    
    while (true) {
      // The artifact the human approves at Gate 2. Default = the generic deterministic
      // scope/evidence/adversarial/synthesis matrix (back-compat). A real researchPrime run
      // injects `buildPlan` (see bin/plan-gate.mjs) so Gate 2 approves the ACTUAL Phase-1
      // research plan — AXIS / candidate branches / stakes vector / foresight receipt — not
      // the boilerplate matrix. `buildPlan` MUST be a pure function of `inputs` so the same
      // inputs serialize to the same bytes and therefore the same planHash (EDIT re-hash + replay).
      const plan = buildPlan
        ? buildPlan({ inputs })
        : planMatrix({ objective: inputs.query || inputs.objective || 'default objective' });
      const planStr = JSON.stringify(plan, null, 2);
      planHash = crypto.createHash('sha256').update(planStr).digest('hex');
      const planPath = path.join(runDir, `plan-${planHash}.json`);
      
      fs.writeFileSync(planPath, planStr, 'utf8');

      if (promptGate2) {
        gate2Decision = await promptGate2({ planPath, planHash, plan });
      } else {
        gate2Decision = 'APPROVE';
      }

      fs.writeFileSync(path.join(runDir, 'gate2-record.json'), JSON.stringify({
        planHash,
        gate2Decision
      }, null, 2), 'utf8');

      if (gate2Decision === 'APPROVE') {
        break;
      } else if (gate2Decision === 'EDIT') {
        gate2Edits++;
        if (gate2Edits > maxEdits) throw new HaltError(`Run halted at Gate 2: exceeded max EDIT cycles (${maxEdits})`);
        if (onEditedPlan) inputs = await onEditedPlan(inputs);
        continue;
      } else if (gate2Decision === 'ABORT') {
        throw new HaltError(`Run halted at Gate 2 with decision ABORT (Artifact: ${planHash})`);
      } else {
        throw new HaltError(`Run halted at Gate 2 with decision ${gate2Decision}`);
      }
    }

    // Validate state machine reaches execution
    validateExecutionState(runDir, triageResult.triageHash, planHash);

    if (approvalProvider) {
      approvalProvider.validateReplayBinding(triageResult.triageHash, planHash);
    }

    // Emit canonical governance record
    const governanceRecord = {
      schemaVersion: CURRENT_SCHEMA_VERSION,
      triageHash: triageResult.triageHash,
      gate1Decision: triageResult.decision,
      planHash: planHash,
      gate2Decision: gate2Decision,
      lockedGovernorOutput: lockedGovernorOutput,
      hostApprovalProvider: providerIdentity,
      skill: skill
    };

    validate(governanceRecord);

    const govPath = path.join(runDir, 'governance.json');
    fs.writeFileSync(govPath, JSON.stringify(governanceRecord, null, 2), 'utf8');

    return { triageHash: triageResult.triageHash, planHash, governanceRecord };
  } catch (err) {
    if (err instanceof HaltError || err.name === 'HaltError') {
      const haltRecord = {
        status: 'HALTED',
        reason: err.message,
        timestamp: new Date().toISOString()
      };
      fs.writeFileSync(path.join(runDir, 'HALT-RECORD.json'), JSON.stringify(haltRecord, null, 2), 'utf8');
    }
    throw err;
  }
}


