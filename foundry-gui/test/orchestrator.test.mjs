import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { SleepDaemon } from '../src/daemon.mjs';
import { DBManager } from '../src/database.mjs';
import { generateSkillGraphChart } from '../src/daemon.mjs';

function createTempDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function removeDirRecursive(dirPath) {
  if (fs.existsSync(dirPath)) {
    fs.rmSync(dirPath, { recursive: true, force: true });
  }
}

describe('Conversational Orchestrator & Platform-Agnostic Tools - Wave 3', () => {
  let tempDbDir;
  let tempWatchDir;
  let tempSkillsDir;
  let dbPath;
  let activeDaemons = [];

  beforeEach(() => {
    tempDbDir = createTempDir('sleep-engine-orchestrator-db-');
    tempWatchDir = createTempDir('sleep-engine-orchestrator-watch-');
    tempSkillsDir = createTempDir('sleep-engine-orchestrator-skills-');
    dbPath = path.join(tempDbDir, 'test.db');
  });

  afterEach(() => {
    activeDaemons.forEach(d => { try { d.stop(); } catch {} });
    activeDaemons.length = 0;
    removeDirRecursive(tempDbDir);
    removeDirRecursive(tempWatchDir);
    removeDirRecursive(tempSkillsDir);
  });

  test('Skill creation flow - Opt-out of Adversarial Interview', async () => {
    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      skillsDir: tempSkillsDir,
      port: 0
    });
    activeDaemons.push(daemon);
    daemon.start();

    // 1. Initial State should be idle
    let state = daemon.db.getOrchestratorState();
    assert.equal(state.status, 'idle');

    // 2. Send create skill command
    let response = await daemon.handleChatMessage('create skill math-solver');
    assert.ok(response.includes('math-solver'));
    assert.ok(response.includes('Crucible'));
    state = daemon.db.getOrchestratorState();
    assert.equal(state.status, 'awaiting_north_star');
    assert.equal(state.skillName, 'math-solver');

    // 3. Confirm North Star
    response = await daemon.handleChatMessage('yes');
    assert.ok(response.includes('North Star locked'));
    state = daemon.db.getOrchestratorState();
    assert.equal(state.status, 'awaiting_icon');

    // 4. Specify custom icon
    response = await daemon.handleChatMessage('🔢');
    assert.ok(response.includes('Icon: 🔢'));
    state = daemon.db.getOrchestratorState();
    assert.equal(state.status, 'awaiting_adversarial_opt_in');

    // 5. Opt-out of Adversarial Interview
    response = await daemon.handleChatMessage('no');
    assert.ok(response.includes('Foreman · Build Complete'));
    assert.ok(response.includes('math-solver'));
    
    // State should reset to idle
    state = daemon.db.getOrchestratorState();
    assert.equal(state.status, 'idle');

    // Verify SKILL.md was written
    const skillFilePath = path.join(tempSkillsDir, 'math-solver', 'SKILL.md');
    assert.ok(fs.existsSync(skillFilePath), 'SKILL.md file should exist');
    const skillContent = fs.readFileSync(skillFilePath, 'utf8');
    assert.ok(skillContent.includes('name: math-solver'));
    assert.ok(skillContent.includes('Icon: 🔢'));

    // Verify skill is indexed in SQLite database
    const skillDb = daemon.db.getSkillByUri('foundry://skills/math-solver');
    assert.ok(skillDb);
    assert.equal(skillDb.name, 'math-solver');
  });

  test('Skill creation flow - Opt-in to Adversarial Interview', async () => {
    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      skillsDir: tempSkillsDir,
      port: 0
    });
    activeDaemons.push(daemon);
    daemon.start();

    // 1. Send create skill command
    await daemon.handleChatMessage('create skill code-linter');
    // 2. Confirm North Star
    await daemon.handleChatMessage('yes');
    // 3. Specify custom icon
    await daemon.handleChatMessage('🧹');
    // 4. Opt-in to Adversarial Interview
    let response = await daemon.handleChatMessage('yes');
    assert.ok(response.includes('Skeptic'));
    let state = daemon.db.getOrchestratorState();
    assert.equal(state.status, 'adversarial_interview');
    assert.equal(state.currentGrillQuestionIndex, 0);

    // 5. Answer Skeptic Q1
    response = await daemon.handleChatMessage('Use process.on to catch rejections.');
    assert.ok(response.includes('Contrarian'));
    state = daemon.db.getOrchestratorState();
    assert.equal(state.status, 'adversarial_interview');
    assert.equal(state.currentGrillQuestionIndex, 1);

    // 6. Answer Contrarian Q2
    response = await daemon.handleChatMessage('Pins package versions.');
    assert.ok(response.includes('Analyst'));
    state = daemon.db.getOrchestratorState();
    assert.equal(state.status, 'adversarial_interview');
    assert.equal(state.currentGrillQuestionIndex, 2);

    // 7. Answer Analyst Q3
    response = await daemon.handleChatMessage('Locks the North Star in a schema file.');
    assert.ok(response.includes('Foreman · Build Complete'));
    state = daemon.db.getOrchestratorState();
    assert.equal(state.status, 'idle');

    // Verify SKILL.md was written with Adversarial Interview summary
    const skillFilePath = path.join(tempSkillsDir, 'code-linter', 'SKILL.md');
    assert.ok(fs.existsSync(skillFilePath), 'SKILL.md file should exist');
    const skillContent = fs.readFileSync(skillFilePath, 'utf8');
    assert.ok(skillContent.includes('Adversarial Interview Summary'));
    assert.ok(skillContent.includes('Use process.on to catch rejections.'));
    assert.ok(skillContent.includes('Pins package versions.'));
    assert.ok(skillContent.includes('Locks the North Star in a schema file.'));
  });

  test('generateSkillGraphChart dependency visualization matches Anchor style', () => {
    const db = new DBManager(dbPath);
    
    // Manually insert some skills to construct a dependency tree
    db.db.prepare(`
      INSERT INTO skills (uri, name, description, file_path, hash, content, dependencies)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(
      'foundry://skills/parent-skill',
      'parent-skill',
      'A skill that depends on child',
      'C:\\parent\\SKILL.md',
      'hash1',
      'content1',
      JSON.stringify(['foundry://skills/child-skill'])
    );

    db.db.prepare(`
      INSERT INTO skills (uri, name, description, file_path, hash, content, dependencies)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).run(
      'foundry://skills/child-skill',
      'child-skill',
      'A child skill',
      'C:\\child\\SKILL.md',
      'hash2',
      'content2',
      '[]'
    );

    const chart = generateSkillGraphChart(db);
    
    assert.ok(chart.includes('### Discovered Skill Graph'));
    assert.ok(chart.includes('- **parent-skill**'));
    assert.ok(chart.includes('  └── **child-skill**'));
    assert.ok(chart.includes('- **child-skill** *(no dependencies)*'));

    db.close();
  });

  test('HTTP API routes for conversational chat', async () => {
    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      skillsDir: tempSkillsDir,
      port: 0
    });
    activeDaemons.push(daemon);
    daemon.start();

    const actualPort = await new Promise((resolve) => {
      daemon.on('serverStarted', (port) => resolve(port));
    });

    // 1. Post a chat message
    const postRes = await fetch(`http://localhost:${actualPort}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'create skill math-solver' })
    });
    assert.equal(postRes.status, 200);
    const postData = await postRes.json();
    assert.ok(postData.reply.includes('math-solver'));
    assert.equal(postData.history.length, 2); // 1 user message, 1 system message

    // 2. Get chat history
    const getRes = await fetch(`http://localhost:${actualPort}/api/chat/history`);
    assert.equal(getRes.status, 200);
    const getData = await getRes.json();
    assert.equal(getData.length, 2);
    assert.equal(getData[0].sender, 'user');
    assert.equal(getData[0].text, 'create skill math-solver');

    // 3. Clear chat history
    const clearRes = await fetch(`http://localhost:${actualPort}/api/chat/clear`, {
      method: 'POST'
    });
    assert.equal(clearRes.status, 200);
    const clearData = await clearRes.json();
    assert.equal(clearData.success, true);

    const getRes2 = await fetch(`http://localhost:${actualPort}/api/chat/history`);
    const getData2 = await getRes2.json();
    assert.equal(getData2.length, 0, 'History should be empty after clear');
  });

  test('Wave 5 - 5-Step Meta-Skill Creation Pipeline with atomic writes and sub-agent mocks', async () => {
    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      skillsDir: tempSkillsDir,
      port: 0
    });
    activeDaemons.push(daemon);
    daemon.start();

    // Mock the pipeline sub-agents
    let gandalfCalled = false;
    let researchPrimeCalled = false;
    let crucibleCalled = false;
    let registryCalled = false;

    daemon.runGandalfInterrogation = async (intent) => {
      gandalfCalled = true;
      assert.equal(intent, 'Build a solver for linear equations');
      // Return empty representing building from scratch
      return [];
    };

    daemon.runResearchPrimeScour = async (skillName, intent) => {
      researchPrimeCalled = true;
      assert.equal(skillName, 'equation-solver');
      assert.equal(intent, 'Build a solver for linear equations');
      return 'Mock recommendations from literature';
    };

    daemon.runCruciblePlanForging = async (skillName, intent, context) => {
      crucibleCalled = true;
      assert.equal(skillName, 'equation-solver');
      assert.equal(intent, 'Build a solver for linear equations');
      assert.equal(context.researchRecommendations, 'Mock recommendations from literature');
      assert.equal(context.buildFromScratch, true);
      
      // Return custom formatted structure
      return `---\nname: ${skillName}\ndescription: ${intent}\ndependencies: []\n---\n# ${skillName}\n\nIcon: ⚙️\nNorth Star: ${intent}\n`;
    };

    const originalCommit = daemon.commitToAnchorRegistry.bind(daemon);
    daemon.commitToAnchorRegistry = async (skillName, fileContent) => {
      registryCalled = true;
      
      // Verify atomic write: file does not exist before commit
      const skillFilePath = path.join(tempSkillsDir, skillName, 'SKILL.md');
      assert.ok(!fs.existsSync(skillFilePath), 'Target file should not exist yet before commit');
      
      // Execute original commit
      const res = await originalCommit(skillName, fileContent);
      
      // Verify file exists now
      assert.ok(fs.existsSync(skillFilePath), 'Target file should exist after commit');
      return res;
    };

    // Execute the pipeline via direct intent submission (command with --pipeline)
    const response = await daemon.handleChatMessage('create skill equation-solver --pipeline');
    assert.ok(response.includes('equation-solver'));
    assert.ok(response.includes('Build Complete'));

    // Assert that all sub-agent steps were called
    assert.ok(gandalfCalled, 'Gandalf should be invoked');
    assert.ok(researchPrimeCalled, 'researchPrime should be invoked');
    assert.ok(crucibleCalled, 'Crucible should be invoked');
    assert.ok(registryCalled, 'Anchor Registry should be invoked');

    // Verify Markdown content and DB registration
    const finalFilePath = path.join(tempSkillsDir, 'equation-solver', 'SKILL.md');
    assert.ok(fs.existsSync(finalFilePath), 'SKILL.md should exist');
    const content = fs.readFileSync(finalFilePath, 'utf8');
    assert.ok(content.includes('name: equation-solver'));
    assert.ok(content.includes('North Star: Build a solver for linear equations'));

    const dbSkill = daemon.db.getSkillByUri('foundry://skills/equation-solver');
    assert.ok(dbSkill);
    assert.equal(dbSkill.name, 'equation-solver');
  });

  test('Wave 5 - Pipeline integrated with interactive conversation flow', async () => {
    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      skillsDir: tempSkillsDir,
      port: 0
    });
    activeDaemons.push(daemon);
    daemon.start();

    let pipelineCalled = false;
    daemon.executeMetaSkillPipeline = async (skillName, intent, options) => {
      pipelineCalled = true;
      assert.equal(skillName, 'interactive-skill');
      assert.equal(intent, 'Create a robust skill for \'interactive-skill\' that executes its capabilities without regressing existing features.');
      assert.equal(options.icon, '🔮');
      assert.deepEqual(options.grillAnswers, []);
      
      // Actually write the file for assertions to pass
      const targetDir = path.join(tempSkillsDir, skillName);
      fs.mkdirSync(targetDir, { recursive: true });
      fs.writeFileSync(path.join(targetDir, 'SKILL.md'), `---\nname: ${skillName}\ndescription: test\ndependencies: []\n---\n# ${skillName}`, 'utf8');
      daemon.db.indexSkills(tempSkillsDir);
      return {};
    };

    // Run interactive flow
    await daemon.handleChatMessage('create skill interactive-skill');
    await daemon.handleChatMessage('yes');
    await daemon.handleChatMessage('🔮');
    const response = await daemon.handleChatMessage('no'); // opt-out of adversarial

    assert.ok(response.includes('Build Complete'));
    assert.ok(pipelineCalled, 'Meta-Skill pipeline should be executed when finalizing interactive skill creation');
  });
});
