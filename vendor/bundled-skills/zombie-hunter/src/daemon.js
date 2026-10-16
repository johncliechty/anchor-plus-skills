const { DatabaseSync } = require('node:sqlite');
const crypto = require('node:crypto');
const path = require('node:path');

class TelemetryDaemon {
    constructor(dbPath, encryptionKey) {
        this.dbPath = dbPath || path.join(__dirname, '..', 'telemetry.db');
        // Derive a 32-byte key for AES-256
        this.key = crypto.scryptSync(encryptionKey || 'default_secure_key', 'salt', 32);
        
        this.db = new DatabaseSync(this.dbPath);
        this.init();
        
        this.isRunning = false;
        this.intervalId = null;
    }

    init() {
        this.db.exec(`
            CREATE TABLE IF NOT EXISTS suspicious_processes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                processId TEXT,
                name TEXT,
                executablePath TEXT,
                commandLine TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        `);
    }

    encrypt(text) {
        if (!text) return text;
        const iv = crypto.randomBytes(16);
        const cipher = crypto.createCipheriv('aes-256-gcm', this.key, iv);
        let encrypted = cipher.update(text, 'utf8', 'hex');
        encrypted += cipher.final('hex');
        const authTag = cipher.getAuthTag().toString('hex');
        return `${iv.toString('hex')}:${authTag}:${encrypted}`;
    }

    decrypt(text) {
        if (!text) return text;
        const parts = text.split(':');
        if (parts.length !== 3) return text;
        const [ivHex, authTagHex, encryptedHex] = parts;
        const decipher = crypto.createDecipheriv('aes-256-gcm', this.key, Buffer.from(ivHex, 'hex'));
        decipher.setAuthTag(Buffer.from(authTagHex, 'hex'));
        let decrypted = decipher.update(encryptedHex, 'hex', 'utf8');
        decrypted += decipher.final('utf8');
        return decrypted;
    }

    logSuspicious(processData) {
        const stmt = this.db.prepare(`
            INSERT INTO suspicious_processes (processId, name, executablePath, commandLine)
            VALUES (?, ?, ?, ?)
        `);
        
        stmt.run(
            this.encrypt(processData.processId),
            this.encrypt(processData.name),
            this.encrypt(processData.executablePath),
            this.encrypt(processData.commandLine)
        );
    }

    getSuspicious() {
        const stmt = this.db.prepare(`SELECT * FROM suspicious_processes`);
        const rows = stmt.all();
        return rows.map(row => ({
            id: row.id,
            processId: this.decrypt(row.processId),
            name: this.decrypt(row.name),
            executablePath: this.decrypt(row.executablePath),
            commandLine: this.decrypt(row.commandLine),
            timestamp: row.timestamp
        }));
    }

    cleanOldRecords(retentionDays = 7) {
        const stmt = this.db.prepare(`
            DELETE FROM suspicious_processes 
            WHERE timestamp < datetime('now', '-${retentionDays} days')
            AND id NOT IN (
                SELECT id FROM suspicious_processes ORDER BY timestamp DESC, id ASC LIMIT 1
            )
        `);
        stmt.run();
    }

    start(discoveryModule, intervalMs = 60000) {
        if (this.isRunning) return;
        this.isRunning = true;
        this.discoveryModule = discoveryModule;
        
        this.intervalId = setInterval(() => {
            const processes = this.discoveryModule.discover();
            for (const p of processes) {
                this.logSuspicious(p);
            }
            this.cleanOldRecords(7); // Run sanitization policy
        }, intervalMs);
    }

    stop() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
        this.isRunning = false;
    }

    close() {
        this.stop();
        this.db.close();
    }
}

module.exports = { TelemetryDaemon };
