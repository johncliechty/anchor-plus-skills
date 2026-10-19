import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { SleepDaemon } from '../src/daemon.mjs';
import { DBManager } from '../src/database.mjs';
import { validateAgentPayload, parseAndValidateSkill } from '../src/schema.mjs';
import { CanaryRunner } from '../src/canary.mjs';
import { resolveFoundryUri } from '../src/resolver.mjs';


function createTempDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function removeDirRecursive(dirPath) {
  if (fs.existsSync(dirPath)) {
    fs.rmSync(dirPath, { recursive: true, force: true });
  }
}

describe('Sleep & Learning Engine - Wave 1', () => {
  let tempDbDir;
  let tempWatchDir;
  let dbPath;
  let mockScriptPath;

  beforeEach(() => {
    tempDbDir = createTempDir('sleep-engine-db-');
    tempWatchDir = createTempDir('sleep-engine-watch-');
    dbPath = path.join(tempDbDir, 'test.db');
    mockScriptPath = path.join(tempDbDir, 'mock-research-prime.mjs');
    fs.writeFileSync(mockScriptPath, `
      process.stdout.write(JSON.stringify({
        summary: "Synthesized mock skill update",
        metaRecipe: {
          skills: [],
          systemPromptUpdates: []
        }
      }));
    `);
  });

  afterEach(() => {
    removeDirRecursive(tempDbDir);
    removeDirRecursive(tempWatchDir);
  });

  test('DBManager state tracking', () => {
    const db = new DBManager(dbPath);
    
    // Initial state
    assert.equal(db.getUsageCount(), 0);
    assert.ok(db.getLastRunTimestamp() <= Date.now());

    // Set & Get
    db.setUsageCount(5);
    assert.equal(db.getUsageCount(), 5);

    // Increment
    const newCount = db.incrementUsageCount();
    assert.equal(newCount, 6);
    assert.equal(db.getUsageCount(), 6);

    // Last run timestamp
    const futureTime = Date.now() + 10000;
    db.setLastRunTimestamp(futureTime);
    assert.equal(db.getLastRunTimestamp(), futureTime);

    // Reset
    db.reset();
    assert.equal(db.getUsageCount(), 0);
    assert.ok(db.getLastRunTimestamp() <= Date.now());

    db.close();
  });

  test('SleepDaemon - Unit triggers on count', async () => {
    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      usageThreshold: 3,
      timeThresholdMs: 1000 * 60, // 1 minute
      researchPrimeCommand: `node ${mockScriptPath}`
    });

    let eventTriggered = false;
    let triggerReason = null;

    daemon.on('sleepCycleTriggered', (event) => {
      eventTriggered = true;
      triggerReason = event.reason;
    });

    const triggerPromise = new Promise((resolve) => {
      daemon.once('sleepCycleTriggered', resolve);
    });

    // Manually handle new journals (simulated)
    daemon.handleNewJournal(); // count = 1
    assert.equal(eventTriggered, false);

    daemon.handleNewJournal(); // count = 2
    assert.equal(eventTriggered, false);

    daemon.handleNewJournal(); // count = 3 -> should trigger
    
    await triggerPromise;
    assert.equal(eventTriggered, true);
    assert.equal(triggerReason, 'count');
    
    // Count should be reset after trigger
    assert.equal(daemon.db.getUsageCount(), 0);

    daemon.stop();
  });

  test('SleepDaemon - Unit triggers on time', async () => {
    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      usageThreshold: 12,
      timeThresholdMs: 50, // 50ms for testing
      researchPrimeCommand: `node ${mockScriptPath}`
    });

    // Mock last run to be in the past
    daemon.db.setLastRunTimestamp(Date.now() - 100);

    let eventTriggered = false;
    let triggerReason = null;

    daemon.on('sleepCycleTriggered', (event) => {
      eventTriggered = true;
      triggerReason = event.reason;
    });

    const triggerPromise = new Promise((resolve) => {
      daemon.once('sleepCycleTriggered', resolve);
    });

    // Check triggers directly
    daemon.checkTriggers();
    
    await triggerPromise;
    assert.equal(eventTriggered, true);
    assert.equal(triggerReason, 'time');

    daemon.stop();
  });

  test('SleepDaemon - Watcher integration triggers sleep cycle on 12 journal additions', async () => {
    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      usageThreshold: 12,
      timeThresholdMs: 1000000, // high threshold to avoid time trigger
      researchPrimeCommand: `node ${mockScriptPath}`
    });

    // Start daemon
    daemon.start();

    // Wait for chokidar to be ready
    await new Promise((resolve) => {
      daemon.watcher.on('ready', resolve);
    });

    let eventTriggered = false;
    let triggerReason = null;

    daemon.on('sleepCycleTriggered', (event) => {
      eventTriggered = true;
      triggerReason = event.reason;
    });

    const triggerPromise = new Promise((resolve) => {
      daemon.once('sleepCycleTriggered', resolve);
    });

    // Add 12 dummy files with brief spacing to ensure filesystem registry
    for (let i = 1; i <= 12; i++) {
      fs.writeFileSync(path.join(tempWatchDir, `journal-${i}.json`), JSON.stringify({ id: i }));
      // Give a tiny pause to allow chokidar to process
      await new Promise((resolve) => setTimeout(resolve, 15));
    }

    await triggerPromise;

    assert.equal(eventTriggered, true, 'Sleep cycle should trigger after 12 file additions');
    assert.equal(triggerReason, 'count');
    assert.equal(daemon.db.getUsageCount(), 0, 'Counter should reset to 0');

    daemon.stop();
  });

  test('validateAgentPayload validation logic', () => {
    const validPayload = {
      timestamp: Date.now(),
      version: "1.0.0",
      northStar: "Learn coding",
      summary: "Completed work",
      metaRecipe: {
        skills: [
          { name: "coder", recipe: "Write tests", changes: ["add test suite"] }
        ],
        systemPromptUpdates: ["update system prompt"]
      },
      timeline: [
        { timestamp: Date.now(), event: "Run", status: "success", details: "all good" }
      ]
    };

    // Should pass validation
    assert.equal(validateAgentPayload(validPayload), true);

    // Missing fields
    assert.throws(() => validateAgentPayload({ ...validPayload, timestamp: undefined }));
    assert.throws(() => validateAgentPayload({ ...validPayload, version: undefined }));
    assert.throws(() => validateAgentPayload({ ...validPayload, northStar: undefined }));
    assert.throws(() => validateAgentPayload({ ...validPayload, summary: undefined }));
    assert.throws(() => validateAgentPayload({ ...validPayload, metaRecipe: undefined }));
    assert.throws(() => validateAgentPayload({ ...validPayload, timeline: undefined }));

    // Invalid types/schemas
    assert.throws(() => validateAgentPayload({ ...validPayload, timestamp: "not a number" }));
    assert.throws(() => validateAgentPayload({ ...validPayload, metaRecipe: { skills: "not an array" } }));
    assert.throws(() => validateAgentPayload({ ...validPayload, timeline: [{ timestamp: Date.now(), event: "Run", status: "invalid-status" }] }));
  });

  test('SleepDaemon - Wave 2 executes researchPrime, validates payload schema, and writes agent-payload.json', async () => {
    const mockScriptPath = path.join(tempDbDir, 'mock-research-prime.mjs');
    fs.writeFileSync(mockScriptPath, `
      import fs from 'node:fs';
      // read stdin to verify it works
      const input = fs.readFileSync(0, 'utf8');
      // output valid JSON
      process.stdout.write(JSON.stringify({
        summary: "Synthesized mock skill update",
        metaRecipe: {
          skills: [
            { name: "mock-skill", recipe: "Always return true", changes: ["optimized return statement"] }
          ],
          systemPromptUpdates: ["Avoid extra logs"]
        }
      }));
    `);

    // Write a dummy North Star file to verify loading
    const mockNorthStarPath = path.join(tempDbDir, 'NORTH-STAR.md');
    fs.writeFileSync(mockNorthStarPath, 'Mock North Star Objective');

    // Set up daemon
    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      usageThreshold: 2,
      timeThresholdMs: 1000000,
      researchPrimeCommand: `node ${mockScriptPath}`,
      payloadDir: tempDbDir, // write to temp dir
      northStarPath: mockNorthStarPath
    });

    daemon.start();

    // Wait for watcher
    await new Promise((resolve) => daemon.watcher.on('ready', resolve));

    let cycleTriggered = false;
    let eventData = null;

    daemon.on('sleepCycleTriggered', (ev) => {
      cycleTriggered = true;
      eventData = ev;
    });

    // Create some dummy journals
    fs.writeFileSync(path.join(tempWatchDir, 'journal-1.json'), '{"id":1,"entry":"worked on python code"}');
    fs.writeFileSync(path.join(tempWatchDir, 'journal-2.json'), '{"id":2,"entry":"updated ts type definitions"}');

    // Wait for the cycle to trigger (since usageThreshold is 2, it should trigger)
    for (let i = 0; i < 20; i++) {
      if (cycleTriggered) break;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }

    assert.equal(cycleTriggered, true, 'Sleep cycle should trigger and complete');
    assert.ok(fs.existsSync(daemon.payloadPath), 'agent-payload.json should be created');

    // Load and check the generated payload
    const payloadContent = JSON.parse(fs.readFileSync(daemon.payloadPath, 'utf8'));
    
    assert.equal(payloadContent.northStar, 'Mock North Star Objective');
    assert.equal(payloadContent.summary, 'Synthesized mock skill update');
    assert.equal(payloadContent.metaRecipe.skills[0].name, 'mock-skill');
    assert.equal(payloadContent.metaRecipe.skills[0].recipe, 'Always return true');
    assert.equal(payloadContent.metaRecipe.skills[0].changes[0], 'optimized return statement');
    assert.equal(payloadContent.metaRecipe.systemPromptUpdates[0], 'Avoid extra logs');
    
    // Timeline checking
    assert.ok(Array.isArray(payloadContent.timeline));
    assert.equal(payloadContent.timeline.length, 1);
    assert.equal(payloadContent.timeline[0].status, 'success');
    assert.equal(payloadContent.timeline[0].event, 'Sleep Cycle Triggered (count)');
    assert.equal(payloadContent.timeline[0].details, 'Synthesized mock skill update');

    daemon.stop();
  });

  test('SleepDaemon - Wave 2 handles researchPrime failure and logs error in database timeline', async () => {
    const mockScriptPath = path.join(tempDbDir, 'mock-research-prime-fail.mjs');
    fs.writeFileSync(mockScriptPath, `
      process.stderr.write("Simulated CLI error");
      process.exit(1);
    `);

    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      usageThreshold: 1,
      timeThresholdMs: 1000000,
      researchPrimeCommand: `node ${mockScriptPath}`,
      payloadDir: tempDbDir
    });

    daemon.start();

    await new Promise((resolve) => daemon.watcher.on('ready', resolve));

    let cycleFailed = false;
    let failureError = null;

    daemon.on('sleepCycleFailed', (ev) => {
      cycleFailed = true;
      failureError = ev.error;
    });

    // Create 1 dummy journal
    fs.writeFileSync(path.join(tempWatchDir, 'journal-1.json'), '{"id":1}');

    for (let i = 0; i < 20; i++) {
      if (cycleFailed) break;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }

    assert.equal(cycleFailed, true, 'Sleep cycle should fail');
    assert.ok(failureError.includes('exited with code 1'), 'Error should mention the exit code');

    // Check that failure was recorded in the database
    const timeline = daemon.db.getTimeline();
    assert.equal(timeline.length, 1);
    assert.equal(timeline[0].status, 'failure');
    assert.ok(timeline[0].details.includes('exited with code 1'));

    daemon.stop();
  });

  test('CanaryRunner - unit validation checks', async () => {
    const tempCanariesDir = createTempDir('sleep-engine-canaries-');
    const runner = new CanaryRunner(tempCanariesDir);

    // No files in directory -> should pass
    await runner.validate({ skills: [] });

    // 1. require_skill test
    fs.writeFileSync(path.join(tempCanariesDir, 'test-require-skill.json'), JSON.stringify({
      name: "Require Skill Suite",
      rules: [{ type: "require_skill", skill: "coder" }]
    }));

    // Should fail when coder is missing
    await assert.rejects(() => runner.validate({ skills: [] }), /Required skill "coder" is missing/);

    // Should pass when coder is present
    await runner.validate({ skills: [{ name: "coder", recipe: "Write code" }] });

    // Cleanup and create next suite
    fs.unlinkSync(path.join(tempCanariesDir, 'test-require-skill.json'));

    // 2. recipe_contains and recipe_not_contains
    fs.writeFileSync(path.join(tempCanariesDir, 'test-recipe-content.json'), JSON.stringify({
      name: "Recipe Content Suite",
      rules: [
        { type: "recipe_contains", skill: "coder", substring: "Write tests" },
        { type: "recipe_not_contains", skill: "coder", substring: "TODO" }
      ]
    }));

    // Should fail when substring is missing
    await assert.rejects(
      () => runner.validate({ skills: [{ name: "coder", recipe: "Write code" }] }),
      /recipe does not contain "Write tests"/
    );

    // Should fail when forbidden substring is present
    await assert.rejects(
      () => runner.validate({ skills: [{ name: "coder", recipe: "Write tests. TODO: optimize" }] }),
      /recipe contains forbidden substring "TODO"/
    );

    // Should pass when matches both
    await runner.validate({ skills: [{ name: "coder", recipe: "Write tests. Ensure they pass" }] });

    fs.unlinkSync(path.join(tempCanariesDir, 'test-recipe-content.json'));

    // Cleanup temp canaries dir
    removeDirRecursive(tempCanariesDir);
  });

  test('SleepDaemon - Wave 3 canary validation success commits payload', async () => {
    const tempCanariesDir = createTempDir('sleep-engine-canaries-');
    
    // Write canary rule: requires 'coder' skill to exist and contain 'Write tests'
    fs.writeFileSync(path.join(tempCanariesDir, 'canary.json'), JSON.stringify({
      name: "Canary Check",
      rules: [
        { type: "require_skill", skill: "coder" },
        { type: "recipe_contains", skill: "coder", substring: "Write tests" }
      ]
    }));

    const mockScriptPath = path.join(tempDbDir, 'mock-research-prime-pass.mjs');
    fs.writeFileSync(mockScriptPath, `
      process.stdout.write(JSON.stringify({
        summary: "Canary pass updates",
        metaRecipe: {
          skills: [
            { name: "coder", recipe: "Write tests and code" }
          ]
        }
      }));
    `);

    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      usageThreshold: 1,
      timeThresholdMs: 1000000,
      researchPrimeCommand: `node ${mockScriptPath}`,
      payloadDir: tempDbDir,
      canariesDir: tempCanariesDir
    });

    daemon.start();
    await new Promise((resolve) => daemon.watcher.on('ready', resolve));

    let cycleTriggered = false;
    daemon.on('sleepCycleTriggered', () => {
      cycleTriggered = true;
    });

    // Seed database usage count
    daemon.db.setUsageCount(1);
    daemon.db.setLastRunTimestamp(Date.now());

    // Trigger cycle
    await daemon.triggerSleepCycle('count');

    assert.equal(cycleTriggered, true, 'Sleep cycle should succeed');
    assert.ok(fs.existsSync(daemon.payloadPath), 'Payload should be written');
    
    const payload = JSON.parse(fs.readFileSync(daemon.payloadPath, 'utf8'));
    assert.equal(payload.summary, "Canary pass updates");
    assert.equal(payload.metaRecipe.skills[0].name, "coder");

    // DB usage count should be reset
    assert.equal(daemon.db.getUsageCount(), 0);

    daemon.stop();
    removeDirRecursive(tempCanariesDir);
  });

  test('SleepDaemon - Wave 3 canary validation failure performs rollback', async () => {
    const tempCanariesDir = createTempDir('sleep-engine-canaries-');
    
    // Write canary rule: requires 'coder' skill to exist
    fs.writeFileSync(path.join(tempCanariesDir, 'canary.json'), JSON.stringify({
      name: "Canary Check",
      rules: [
        { type: "require_skill", skill: "coder" }
      ]
    }));

    // Mock researchPrime returns a different skill, which fails the canary
    const mockScriptPath = path.join(tempDbDir, 'mock-research-prime-fail.mjs');
    fs.writeFileSync(mockScriptPath, `
      process.stdout.write(JSON.stringify({
        summary: "Canary fail updates",
        metaRecipe: {
          skills: [
            { name: "designer", recipe: "Create premium look" }
          ]
        }
      }));
    `);

    // Let's create an existing payload file to verify it is NOT overwritten
    const existingPayloadPath = path.join(tempDbDir, 'agent-payload.json');
    const originalPayload = {
      timestamp: 1000,
      version: "1.0.0",
      northStar: "Original objective",
      summary: "Original summary",
      metaRecipe: {
        skills: [{ name: "coder", recipe: "Original recipe" }]
      },
      timeline: []
    };
    fs.writeFileSync(existingPayloadPath, JSON.stringify(originalPayload, null, 2), 'utf8');

    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      usageThreshold: 1,
      timeThresholdMs: 1000000,
      researchPrimeCommand: `node ${mockScriptPath}`,
      payloadDir: tempDbDir,
      canariesDir: tempCanariesDir
    });

    daemon.start();
    await new Promise((resolve) => daemon.watcher.on('ready', resolve));

    let cycleFailed = false;
    let failureError = null;
    daemon.on('sleepCycleFailed', (ev) => {
      cycleFailed = true;
      failureError = ev.error;
    });

    // Seed database usage count and timestamp to check rollback
    const originalTimestamp = Date.now() - 5000;
    daemon.db.setUsageCount(12);
    daemon.db.setLastRunTimestamp(originalTimestamp);

    // Trigger sleep cycle (which we expect to fail)
    await assert.rejects(
      () => daemon.triggerSleepCycle('count'),
      /Required skill "coder" is missing/
    );

    // Ensure the event sleepCycleFailed was emitted
    assert.equal(cycleFailed, true, 'sleepCycleFailed event should be emitted');
    assert.ok(failureError.includes('Required skill "coder" is missing'));

    // Validate that DB state remains unchanged (usage count not reset, timestamp not updated)
    assert.equal(daemon.db.getUsageCount(), 12, 'Usage count should remain unchanged');
    assert.equal(daemon.db.getLastRunTimestamp(), originalTimestamp, 'Timestamp should remain unchanged');

    // Validate that agent-payload.json was NOT overwritten
    const currentPayload = JSON.parse(fs.readFileSync(daemon.payloadPath, 'utf8'));
    assert.equal(currentPayload.summary, "Original summary", 'Payload summary should not have changed');
    assert.equal(currentPayload.metaRecipe.skills[0].name, "coder", 'Payload skills should not have changed');

    // Validate that the failure was logged in the timeline
    const timeline = daemon.db.getTimeline();
    assert.ok(timeline.length > 0);
    const lastEvent = timeline[timeline.length - 1];
    assert.equal(lastEvent.status, 'failure');
    assert.ok(lastEvent.details.includes('Required skill "coder" is missing'));

    daemon.stop();
    removeDirRecursive(tempCanariesDir);
  });

});

describe('Dual-State Architecture & URI Resolver - Wave 1 Extra tests', () => {
  let tempSkillsDir;
  let dbPath;
  let tempDbDir;

  beforeEach(() => {
    tempDbDir = createTempDir('sleep-engine-db-');
    tempSkillsDir = createTempDir('sleep-engine-skills-');
    dbPath = path.join(tempDbDir, 'test.db');
  });

  afterEach(() => {
    removeDirRecursive(tempDbDir);
    removeDirRecursive(tempSkillsDir);
  });

  test('Skill Frontmatter Parsing and Validation', () => {
    const validMarkdown = `---
name: coder
description: A skill that writes robust code.
dependencies:
  - foundry://skills/git-client
---
# Coder Skill
This is the body of the skill.
`;
    const parsed = parseAndValidateSkill(validMarkdown);
    assert.equal(parsed.frontmatter.name, 'coder');
    assert.equal(parsed.frontmatter.description, 'A skill that writes robust code.');
    assert.deepEqual(parsed.frontmatter.dependencies, ['foundry://skills/git-client']);
    assert.ok(parsed.body.includes('This is the body of the skill.'));

    // Missing frontmatter
    assert.throws(() => parseAndValidateSkill('# Just Markdown\nNo frontmatter here.'));

    // Missing description
    assert.throws(() => parseAndValidateSkill(`---
name: bad-skill
---
No description.`));

    // Bad dependencies type
    assert.throws(() => parseAndValidateSkill(`---
name: bad-skill
description: Yes
dependencies: not-an-array
---
Body`));
  });

  test('foundry:// URI Resolver', () => {
    const skillsDir = 'C:\\dev\\skills';
    
    // Skill name only
    const path1 = resolveFoundryUri('foundry://coder', skillsDir);
    assert.equal(path1, path.resolve(skillsDir, 'coder', 'SKILL.md'));

    // With skills/ prefix
    const path2 = resolveFoundryUri('foundry://skills/coder', skillsDir);
    assert.equal(path2, path.resolve(skillsDir, 'coder', 'SKILL.md'));

    // Inner path
    const path3 = resolveFoundryUri('foundry://coder/references/doc.md', skillsDir);
    assert.equal(path3, path.resolve(skillsDir, 'coder', 'references', 'doc.md'));

    // Invalid scheme
    assert.throws(() => resolveFoundryUri('http://coder', skillsDir));
  });

  test('Startup Indexer and Incremental Caching', () => {
    const db = new DBManager(dbPath);

    // Create a skill
    const skillDir = path.join(tempSkillsDir, 'coder');
    fs.mkdirSync(skillDir, { recursive: true });
    
    const skillFilePath = path.join(skillDir, 'SKILL.md');
    const skillContent = `---
name: coder
description: Write code
---
# Coder
`;
    fs.writeFileSync(skillFilePath, skillContent, 'utf8');

    // Run first indexing
    db.indexSkills(tempSkillsDir);

    const skill = db.getSkillByUri('foundry://skills/coder');
    assert.ok(skill);
    assert.equal(skill.name, 'coder');
    assert.equal(skill.description, 'Write code');
    assert.ok(skill.embedding instanceof Float32Array);
    assert.equal(skill.embedding.length, 1536);

    const originalId = skill.id;

    // Run second indexing (unmodified) - should keep the same ID due to caching
    db.indexSkills(tempSkillsDir);
    const skill2 = db.getSkillByUri('foundry://skills/coder');
    assert.equal(skill2.id, originalId, 'ID should not change if file is unmodified');

    // Modify the file
    const updatedContent = `---
name: coder
description: Write updated code
---
# Coder Updated
`;
    fs.writeFileSync(skillFilePath, updatedContent, 'utf8');

    // Run third indexing (modified) - should re-index and obtain a new ID
    db.indexSkills(tempSkillsDir);
    const skill3 = db.getSkillByUri('foundry://skills/coder');
    assert.notEqual(skill3.id, originalId, 'ID should change when file is modified');
    assert.equal(skill3.description, 'Write updated code');

    // Test semantic search
    const results = db.searchSkillsSemantically('writing code', 1);
    assert.equal(results.length, 1);
    assert.equal(results[0].name, 'coder');

    // Delete the file and verify cleanup
    fs.unlinkSync(skillFilePath);
    db.indexSkills(tempSkillsDir);
    const skill4 = db.getSkillByUri('foundry://skills/coder');
    assert.equal(skill4, null, 'Skill should be cleaned up from DB when deleted from disk');

    db.close();
  });
});

describe('MCP Server Integration - Wave 2', () => {
  let tempDbDir;
  let tempSkillsDir;
  let tempWatchDir;
  let dbPath;

  beforeEach(() => {
    tempDbDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sleep-engine-db-mcp-'));
    tempWatchDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sleep-engine-watch-mcp-'));
    tempSkillsDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sleep-engine-skills-mcp-'));
    dbPath = path.join(tempDbDir, 'test.db');
  });

  afterEach(() => {
    if (fs.existsSync(tempDbDir)) fs.rmSync(tempDbDir, { recursive: true, force: true });
    if (fs.existsSync(tempWatchDir)) fs.rmSync(tempWatchDir, { recursive: true, force: true });
    if (fs.existsSync(tempSkillsDir)) fs.rmSync(tempSkillsDir, { recursive: true, force: true });
  });

  test('MCP SSE and JSON-RPC lifecycle', async () => {
    // Seed some skills
    const coderDir = path.join(tempSkillsDir, 'coder');
    fs.mkdirSync(coderDir, { recursive: true });
    fs.writeFileSync(path.join(coderDir, 'SKILL.md'), `---
name: coder
description: Write beautiful code
dependencies:
  - foundry://skills/git-client
---
# Coder
`);

    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      skillsDir: tempSkillsDir,
      port: 0
    });

    daemon.start();

    const actualPort = await new Promise((resolve) => {
      daemon.on('serverStarted', (port) => resolve(port));
    });

    // 1. Establish SSE Connection
    const controller = new AbortController();
    const sseResponse = await fetch(`http://localhost:${actualPort}/api/mcp/sse`, { signal: controller.signal });
    assert.equal(sseResponse.status, 200);
    assert.equal(sseResponse.headers.get('content-type'), 'text/event-stream');

    const reader = sseResponse.body.getReader();
    const decoder = new TextDecoder();

    // Read initial endpoint event
    let buffer = '';
    let endpointUrl = null;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value);
      if (buffer.includes('\n\n')) {
        const lines = buffer.split('\n');
        const eventLine = lines.find(l => l.startsWith('event:'));
        const dataLine = lines.find(l => l.startsWith('data:'));
        if (eventLine && dataLine) {
          assert.equal(eventLine.trim(), 'event: endpoint');
          endpointUrl = dataLine.replace('data:', '').trim();
          break;
        }
      }
    }

    assert.ok(endpointUrl, 'Should receive endpoint URL in event');
    assert.ok(endpointUrl.includes('connectionId='), 'Endpoint URL should contain connectionId');

    // Helper to read next JSON-RPC data message
    async function readNextMessage() {
      let msgBuffer = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        msgBuffer += decoder.decode(value);
        if (msgBuffer.includes('\n\n')) {
          const lines = msgBuffer.split('\n');
          const dataLine = lines.find(l => l.startsWith('data:'));
          if (dataLine) {
            const dataStr = dataLine.replace('data:', '').trim();
            return JSON.parse(dataStr);
          }
        }
      }
    }

    // 2. Call initialize
    const initRes = await fetch(`http://localhost:${actualPort}${endpointUrl}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'initialize',
        params: {
          protocolVersion: '2024-11-05',
          capabilities: {},
          clientInfo: { name: 'test-client', version: '1.0.0' }
        }
      })
    });
    assert.equal(initRes.status, 202);

    const initRespPayload = await readNextMessage();
    assert.equal(initRespPayload.jsonrpc, '2.0');
    assert.equal(initRespPayload.id, 1);
    assert.equal(initRespPayload.result.protocolVersion, '2024-11-05');
    assert.equal(initRespPayload.result.serverInfo.name, 'sleep-engine-mcp');

    // 3. List tools
    const toolsRes = await fetch(`http://localhost:${actualPort}${endpointUrl}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 2,
        method: 'tools/list'
      })
    });
    assert.equal(toolsRes.status, 202);

    const toolsRespPayload = await readNextMessage();
    assert.equal(toolsRespPayload.id, 2);
    const tools = toolsRespPayload.result.tools;
    assert.ok(Array.isArray(tools));
    assert.ok(tools.find(t => t.name === 'get_skill_dependencies'));
    assert.ok(tools.find(t => t.name === 'search_skills_semantically'));

    // 4. Call get_skill_dependencies tool
    const callDepRes = await fetch(`http://localhost:${actualPort}${endpointUrl}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 3,
        method: 'tools/call',
        params: {
          name: 'get_skill_dependencies',
          arguments: { uri: 'coder' }
        }
      })
    });
    assert.equal(callDepRes.status, 202);

    const callDepRespPayload = await readNextMessage();
    assert.equal(callDepRespPayload.id, 3);
    const depData = JSON.parse(callDepRespPayload.result.content[0].text);
    assert.equal(depData.name, 'coder');
    assert.deepEqual(depData.dependencies, ['foundry://skills/git-client']);

    // 5. Call search_skills_semantically tool
    const callSearchRes = await fetch(`http://localhost:${actualPort}${endpointUrl}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 4,
        method: 'tools/call',
        params: {
          name: 'search_skills_semantically',
          arguments: { query: 'beautiful code', limit: 1 }
        }
      })
    });
    assert.equal(callSearchRes.status, 202);

    const callSearchRespPayload = await readNextMessage();
    assert.equal(callSearchRespPayload.id, 4);
    const searchData = JSON.parse(callSearchRespPayload.result.content[0].text);
    assert.equal(searchData.length, 1);
    assert.equal(searchData[0].name, 'coder');

    // 6. Test resources/list
    const resourcesListRes = await fetch(`http://localhost:${actualPort}${endpointUrl}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 5,
        method: 'resources/list'
      })
    });
    assert.equal(resourcesListRes.status, 202);

    const resourcesListPayload = await readNextMessage();
    assert.equal(resourcesListPayload.id, 5);
    assert.ok(Array.isArray(resourcesListPayload.result.resources));
    assert.equal(resourcesListPayload.result.resources[0].name, 'coder');

    // 7. Test resources/read
    const resourcesReadRes = await fetch(`http://localhost:${actualPort}${endpointUrl}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 6,
        method: 'resources/read',
        params: { uri: 'foundry://skills/coder' }
      })
    });
    assert.equal(resourcesReadRes.status, 202);

    const resourcesReadPayload = await readNextMessage();
    assert.equal(resourcesReadPayload.id, 6);
    assert.equal(resourcesReadPayload.result.contents[0].uri, 'foundry://skills/coder');
    assert.ok(resourcesReadPayload.result.contents[0].text.includes('Write beautiful code'));

    controller.abort();
    daemon.stop();
  });
});

describe('Dual-State Data Architecture - Wave 2 File Watcher', () => {
  let tempDbDir;
  let tempSkillsDir;
  let tempWatchDir;
  let dbPath;

  beforeEach(() => {
    tempDbDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sleep-engine-db-w2-'));
    tempWatchDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sleep-engine-watch-w2-'));
    tempSkillsDir = fs.mkdtempSync(path.join(os.tmpdir(), 'sleep-engine-skills-w2-'));
    dbPath = path.join(tempDbDir, 'test.db');
  });

  afterEach(() => {
    if (fs.existsSync(tempDbDir)) fs.rmSync(tempDbDir, { recursive: true, force: true });
    if (fs.existsSync(tempWatchDir)) fs.rmSync(tempWatchDir, { recursive: true, force: true });
    if (fs.existsSync(tempSkillsDir)) fs.rmSync(tempSkillsDir, { recursive: true, force: true });
  });

  test('file watcher detects added, modified, and deleted .md files and updates DB', async () => {
    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      skillsDir: tempSkillsDir,
      port: null
    });

    daemon.start();

    await new Promise((resolve) => {
      daemon.skillsWatcher.on('ready', resolve);
    });

    let dbSkills = daemon.db.db.prepare('SELECT name FROM skills').all();
    assert.equal(dbSkills.length, 0);

    const subfolder = path.join(tempSkillsDir, 'math-skills');
    fs.mkdirSync(subfolder, { recursive: true });

    const newSkillPath = path.join(subfolder, 'addition.md');
    fs.writeFileSync(newSkillPath, `---
name: addition
description: Perform addition of two numbers.
dependencies: []
---
# Addition
Simple math function.
`, 'utf8');

    let found = false;
    for (let i = 0; i < 50; i++) {
      dbSkills = daemon.db.db.prepare('SELECT name, description FROM skills').all();
      if (dbSkills.length === 1 && dbSkills[0].name === 'addition') {
        found = true;
        assert.equal(dbSkills[0].description, 'Perform addition of two numbers.');
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.ok(found, 'Database should hydrate the new skill from the added .md file');

    fs.writeFileSync(newSkillPath, `---
name: addition
description: Perform updated addition of two numbers.
dependencies: []
---
# Addition Updated
Simple math function updated.
`, 'utf8');

    let updated = false;
    for (let i = 0; i < 50; i++) {
      dbSkills = daemon.db.db.prepare('SELECT description FROM skills WHERE name = ?').all('addition');
      if (dbSkills.length === 1 && dbSkills[0].description === 'Perform updated addition of two numbers.') {
        updated = true;
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.ok(updated, 'Database should update when the .md file is modified');

    fs.unlinkSync(newSkillPath);

    let deleted = false;
    for (let i = 0; i < 50; i++) {
      dbSkills = daemon.db.db.prepare('SELECT name FROM skills').all();
      if (dbSkills.length === 0) {
        deleted = true;
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.ok(deleted, 'Database should prune the skill when the .md file is deleted');

    daemon.stop();
  });
});




