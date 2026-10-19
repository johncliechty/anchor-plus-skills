import Database from 'better-sqlite3';
import * as sqliteVec from 'sqlite-vec';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import crypto from 'node:crypto';
import { DEFAULT_DB_PATH } from './config.mjs';
import { parseAndValidateSkill } from './schema.mjs';

/**
 * Generates a deterministic normalized float vector of the specified size.
 * @param {string} text
 * @param {number} dimensions
 * @returns {Float32Array}
 */
export function generateDeterministicEmbedding(text, dimensions = 1536) {
  const vector = new Float32Array(dimensions);
  let seed = 0;
  for (let i = 0; i < text.length; i++) {
    seed = (seed * 31 + text.charCodeAt(i)) & 0xFFFFFFFF;
  }
  
  const a = 1103515245;
  const c = 12345;
  const m = 2147483648;
  
  let current = Math.abs(seed);
  for (let i = 0; i < dimensions; i++) {
    current = (a * current + c) % m;
    vector[i] = (current / m) * 2 - 1;
  }
  
  let sumSq = 0;
  for (let i = 0; i < dimensions; i++) {
    sumSq += vector[i] * vector[i];
  }
  const norm = Math.sqrt(sumSq);
  if (norm > 0) {
    for (let i = 0; i < dimensions; i++) {
      vector[i] /= norm;
    }
  }
  return vector;
}

/**
 * Resolves the database file path and ensures the parent directory exists.
 * @param {string|null} customPath
 * @returns {string} resolved database path
 */
export function getDbPath(customPath = null) {
  if (customPath) return customPath;
  const dir = path.dirname(DEFAULT_DB_PATH);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
  return DEFAULT_DB_PATH;
}

export class DBManager {
  /**
   * @param {string|null} dbPath
   */
  constructor(dbPath = null) {
    this.dbPath = getDbPath(dbPath);
    this.db = new Database(this.dbPath);
    sqliteVec.load(this.db);
    this.init();
  }

  /**
   * Initializes the engine state table.
   */
  init() {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS engine_state (
        key TEXT PRIMARY KEY,
        value TEXT
      );
      
      CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uri TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        file_path TEXT NOT NULL,
        hash TEXT NOT NULL,
        content TEXT NOT NULL,
        dependencies TEXT
      );
      
      CREATE VIRTUAL TABLE IF NOT EXISTS vec_skills USING vec0(
        embedding float[1536]
      );

      CREATE TABLE IF NOT EXISTS telemetry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        cpu_usage REAL NOT NULL,
        memory_usage INTEGER NOT NULL,
        skill_invocations INTEGER NOT NULL
      );
      
      CREATE TABLE IF NOT EXISTS skill_invocations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        skill_name TEXT NOT NULL
      );
    `);
    
    // Seed initial values if not present
    const stmt = this.db.prepare('INSERT OR IGNORE INTO engine_state (key, value) VALUES (?, ?)');
    stmt.run('usage_count', '0');
    stmt.run('last_run_timestamp', String(Date.now()));
    stmt.run('timeline', '[]');
    stmt.run('chat_history', '[]');
    stmt.run('orchestrator_state', JSON.stringify({ status: 'idle' }));
  }

  /**
   * Gets the usage count.
   * @returns {number}
   */
  getUsageCount() {
    const row = this.db.prepare('SELECT value FROM engine_state WHERE key = ?').get('usage_count');
    return row ? parseInt(row.value, 10) : 0;
  }

  /**
   * Sets the usage count.
   * @param {number} count
   */
  setUsageCount(count) {
    this.db.prepare('INSERT OR REPLACE INTO engine_state (key, value) VALUES (?, ?)').run('usage_count', String(count));
  }

  /**
   * Increments the usage count by 1.
   * @returns {number} new count
   */
  incrementUsageCount() {
    const count = this.getUsageCount() + 1;
    this.setUsageCount(count);
    return count;
  }

  /**
   * Gets the timestamp of the last sleep cycle run.
   * @returns {number}
   */
  getLastRunTimestamp() {
    const row = this.db.prepare('SELECT value FROM engine_state WHERE key = ?').get('last_run_timestamp');
    return row ? parseInt(row.value, 10) : Date.now();
  }

  /**
   * Sets the timestamp of the last sleep cycle run.
   * @param {number} timestamp
   */
  setLastRunTimestamp(timestamp) {
    this.db.prepare('INSERT OR REPLACE INTO engine_state (key, value) VALUES (?, ?)').run('last_run_timestamp', String(timestamp));
  }

  /**
   * Resets the usage count and updates the last run timestamp to now.
   */
  reset() {
    this.setUsageCount(0);
    this.setLastRunTimestamp(Date.now());
  }

  /**
   * Gets the timeline array.
   * @returns {Array<object>}
   */
  getTimeline() {
    const row = this.db.prepare('SELECT value FROM engine_state WHERE key = ?').get('timeline');
    return row ? JSON.parse(row.value) : [];
  }

  /**
   * Adds a new event to the chronological timeline.
   * @param {string} event
   * @param {"success"|"failure"|"pending"} status
   * @param {string} [details]
   */
  addTimelineEvent(event, status, details = '') {
    const timeline = this.getTimeline();
    timeline.push({
      timestamp: Date.now(),
      event,
      status,
      details
    });
    this.db.prepare('INSERT OR REPLACE INTO engine_state (key, value) VALUES (?, ?)').run('timeline', JSON.stringify(timeline));
  }

  /**
   * Gets the chat history array.
   * @returns {Array<object>}
   */
  getChatHistory() {
    const row = this.db.prepare('SELECT value FROM engine_state WHERE key = ?').get('chat_history');
    return row ? JSON.parse(row.value) : [];
  }

  /**
   * Sets the chat history array.
   * @param {Array<object>} history
   */
  setChatHistory(history) {
    this.db.prepare('INSERT OR REPLACE INTO engine_state (key, value) VALUES (?, ?)').run('chat_history', JSON.stringify(history));
  }

  /**
   * Adds a new message to the chat history.
   * @param {string} sender
   * @param {string} text
   */
  addChatMessage(sender, text) {
    const history = this.getChatHistory();
    history.push({
      timestamp: Date.now(),
      sender,
      text
    });
    this.setChatHistory(history);
  }

  /**
   * Clears the chat history.
   */
  clearChatHistory() {
    this.setChatHistory([]);
  }

  /**
   * Gets the orchestrator state object.
   * @returns {object}
   */
  getOrchestratorState() {
    const row = this.db.prepare('SELECT value FROM engine_state WHERE key = ?').get('orchestrator_state');
    return row ? JSON.parse(row.value) : { status: 'idle' };
  }

  /**
   * Sets the orchestrator state object.
   * @param {object} state
   */
  setOrchestratorState(state) {
    this.db.prepare('INSERT OR REPLACE INTO engine_state (key, value) VALUES (?, ?)').run('orchestrator_state', JSON.stringify(state));
  }

  /**
   * Scans and indexes the skills directory, using incremental caching (hashing).
   * @param {string} skillsDir
   */
  indexSkills(skillsDir) {
    if (!fs.existsSync(skillsDir)) {
      return;
    }
    
    const findSkillFiles = (dir, fileList = []) => {
      const files = fs.readdirSync(dir);
      for (const file of files) {
        const filePath = path.join(dir, file);
        const stat = fs.statSync(filePath);
        if (stat.isDirectory()) {
          findSkillFiles(filePath, fileList);
        } else if (file.endsWith('.md')) {
          fileList.push(filePath);
        }
      }
      return fileList;
    };
    
    const skillFiles = findSkillFiles(skillsDir);
    const activeFilePaths = new Set();
    
    for (const filePath of skillFiles) {
      activeFilePaths.add(filePath);
      const content = fs.readFileSync(filePath, 'utf8');
      const hash = crypto.createHash('sha256').update(content).digest('hex');
      
      const existing = this.db.prepare('SELECT id, hash FROM skills WHERE file_path = ?').get(filePath);
      if (existing) {
        if (existing.hash === hash) {
          continue;
        }
        this.db.prepare('DELETE FROM vec_skills WHERE rowid = ?').run(BigInt(existing.id));
        this.db.prepare('DELETE FROM skills WHERE id = ?').run(existing.id);
      }
      
      let parsed;
      try {
        parsed = parseAndValidateSkill(content);
      } catch (err) {
        continue;
      }
      
      const { frontmatter } = parsed;
      const uri = `foundry://skills/${frontmatter.name}`;
      const dependencies = frontmatter.dependencies ? JSON.stringify(frontmatter.dependencies) : '[]';
      
      const stmt = this.db.prepare(`
        INSERT INTO skills (uri, name, description, file_path, hash, content, dependencies)
        VALUES (?, ?, ?, ?, ?, ?, ?)
      `);
      const info = stmt.run(uri, frontmatter.name, frontmatter.description, filePath, hash, content, dependencies);
      const id = info.lastInsertRowid;
      
      const embedding = generateDeterministicEmbedding(content);
      const vecStmt = this.db.prepare('INSERT INTO vec_skills (rowid, embedding) VALUES (?, ?)');
      vecStmt.run(BigInt(id), Buffer.from(embedding.buffer));
    }
    
    const dbSkills = this.db.prepare('SELECT id, file_path FROM skills').all();
    for (const dbSkill of dbSkills) {
      if (!activeFilePaths.has(dbSkill.file_path)) {
        this.db.prepare('DELETE FROM vec_skills WHERE rowid = ?').run(BigInt(dbSkill.id));
        this.db.prepare('DELETE FROM skills WHERE id = ?').run(dbSkill.id);
      }
    }
  }

  /**
   * Retrieves a skill and its embedding from the database by its URI.
   * @param {string} uri
   * @returns {object|null}
   */
  getSkillByUri(uri) {
    const skill = this.db.prepare('SELECT * FROM skills WHERE uri = ?').get(uri);
    if (!skill) return null;
    const vec = this.db.prepare('SELECT embedding FROM vec_skills WHERE rowid = ?').get(BigInt(skill.id));
    return {
      ...skill,
      dependencies: JSON.parse(skill.dependencies || '[]'),
      embedding: vec ? new Float32Array(vec.embedding.buffer, vec.embedding.byteOffset, vec.embedding.byteLength / 4) : null
    };
  }

  /**
   * Performs semantic vector search on indexed skills.
   * @param {string} queryText
   * @param {number} [limit]
   * @returns {Array<object>}
   */
  searchSkillsSemantically(queryText, limit = 5) {
    const queryVec = generateDeterministicEmbedding(queryText);
    const matches = this.db.prepare(`
      SELECT s.*, v.distance
      FROM skills s
      JOIN vec_skills v ON s.id = v.rowid
      WHERE v.embedding MATCH ? AND k = ?
      ORDER BY distance
    `).all(Buffer.from(queryVec.buffer), limit);
    return matches.map(m => ({
      ...m,
      dependencies: JSON.parse(m.dependencies || '[]')
    }));
  }

  /**
   * Logs telemetry data into the local store.
   * @param {number} cpuUsage
   * @param {number} memoryUsage
   * @param {number} skillInvocations
   */
  logTelemetry(cpuUsage, memoryUsage, skillInvocations) {
    this.db.prepare(`
      INSERT INTO telemetry (timestamp, cpu_usage, memory_usage, skill_invocations)
      VALUES (?, ?, ?, ?)
    `).run(Date.now(), cpuUsage, memoryUsage, skillInvocations);
  }

  /**
   * Retrieves telemetry logs from the database.
   * @param {number} limit
   * @returns {Array<object>}
   */
  getTelemetry(limit = 100) {
    return this.db.prepare('SELECT * FROM telemetry ORDER BY timestamp DESC LIMIT ?').all(limit);
  }

  /**
   * Records a skill invocation.
   * @param {string} skillName
   */
  recordSkillInvocation(skillName) {
    this.db.prepare(`
      INSERT INTO skill_invocations (timestamp, skill_name)
      VALUES (?, ?)
    `).run(Date.now(), skillName);
  }

  /**
   * Gets the count of skill invocations since a given timestamp.
   * @param {number} timestamp
   * @returns {number}
   */
  getSkillInvocationsCountSince(timestamp) {
    const row = this.db.prepare('SELECT COUNT(*) as count FROM skill_invocations WHERE timestamp >= ?').get(timestamp);
    return row ? row.count : 0;
  }

  /**
   * Closes the database connection.
   */
  close() {
    this.db.close();
  }
}
