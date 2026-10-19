import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { SleepDaemon } from '../src/daemon.mjs';
import { DBManager } from '../src/database.mjs';

function createTempDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function removeDirRecursive(dirPath) {
  if (fs.existsSync(dirPath)) {
    fs.rmSync(dirPath, { recursive: true, force: true });
  }
}

describe('Sleep Engine - Wave 4 Telemetry & Background Loop', () => {
  let tempDbDir;
  let tempWatchDir;
  let dbPath;

  beforeEach(() => {
    tempDbDir = createTempDir('sleep-engine-telemetry-db-');
    tempWatchDir = createTempDir('sleep-engine-telemetry-watch-');
    dbPath = path.join(tempDbDir, 'test.db');
  });

  afterEach(() => {
    removeDirRecursive(tempDbDir);
    removeDirRecursive(tempWatchDir);
  });

  test('DBManager telemetry and invocation logging methods', () => {
    const db = new DBManager(dbPath);

    // Initial state
    assert.deepEqual(db.getTelemetry(), []);
    assert.equal(db.getSkillInvocationsCountSince(0), 0);

    // Record skill invocations
    db.recordSkillInvocation('test-skill-1');
    db.recordSkillInvocation('test-skill-2');
    
    // Check counts
    const countAll = db.getSkillInvocationsCountSince(0);
    assert.equal(countAll, 2);

    const countFuture = db.getSkillInvocationsCountSince(Date.now() + 10000);
    assert.equal(countFuture, 0);

    // Log telemetry
    db.logTelemetry(5.5, 2048, countAll);

    // Verify telemetry logs
    const logs = db.getTelemetry();
    assert.equal(logs.length, 1);
    assert.equal(logs[0].cpu_usage, 5.5);
    assert.equal(logs[0].memory_usage, 2048);
    assert.equal(logs[0].skill_invocations, 2);
    assert.ok(logs[0].timestamp <= Date.now());

    db.close();
  });

  test('SleepDaemon - background worker loop tick and event emission', async () => {
    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      usageThreshold: 100,
      timeThresholdMs: 1000 * 60 * 60, // 1 hour (avoid time trigger)
      telemetryIntervalMs: 25, // 25ms loop for fast testing
      port: 0 // dynamically assign port
    });

    let loggedEventsCount = 0;
    daemon.on('telemetryLogged', (data) => {
      loggedEventsCount++;
      assert.ok(typeof data.cpu === 'number');
      assert.ok(typeof data.memory === 'number');
      assert.ok(typeof data.invocations === 'number');
    });

    daemon.start();

    // Trigger one skill invocation to verify it gets logged in telemetry
    daemon.db.recordSkillInvocation('mcp-skill');

    // Wait for at least 2 ticks to verify periodic loop behavior
    await new Promise((resolve) => {
      const interval = setInterval(() => {
        if (loggedEventsCount >= 2) {
          clearInterval(interval);
          resolve();
        }
      }, 10);
    });

    // Check DB logs
    const telemetryLogs = daemon.db.getTelemetry();
    assert.ok(telemetryLogs.length >= 2, 'Should have logged telemetry at least twice');
    
    // The first or second telemetry tick should have captured the 'mcp-skill' invocation
    const totalInvocationsLogged = telemetryLogs.reduce((sum, log) => sum + log.skill_invocations, 0);
    assert.equal(totalInvocationsLogged, 1, 'Telemetry should have counted the skill invocation');

    // Clean up
    daemon.stop();
  });

  test('SleepDaemon - HTTP telemetry api endpoint retrieval', async () => {
    const daemon = new SleepDaemon({
      watchDir: tempWatchDir,
      dbPath: dbPath,
      usageThreshold: 100,
      timeThresholdMs: 1000 * 60 * 60,
      telemetryIntervalMs: 1000, // 1 second
      port: 0
    });

    daemon.start();

    const actualPort = await new Promise((resolve) => {
      daemon.on('serverStarted', (port) => resolve(port));
    });

    // Manually write one telemetry event to speed up testing
    daemon.db.logTelemetry(12.5, 4096, 3);

    // Call HTTP API endpoint
    const res = await fetch(`http://localhost:${actualPort}/api/telemetry?limit=5`);
    assert.equal(res.status, 200);
    const data = await res.json();
    
    assert.ok(Array.isArray(data));
    assert.ok(data.length >= 1);
    assert.equal(data[0].cpu_usage, 12.5);
    assert.equal(data[0].memory_usage, 4096);
    assert.equal(data[0].skill_invocations, 3);

    daemon.stop();
  });
});
