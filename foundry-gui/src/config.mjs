import path from 'node:path';
import os from 'node:os';

export const DEFAULT_JOURNAL_DIR = path.join(os.homedir(), '.skill-journals');
export const DEFAULT_DB_DIR = path.join(os.homedir(), '.sleep-engine');
export const DEFAULT_DB_PATH = path.join(DEFAULT_DB_DIR, 'sleep-engine.db');

export const USAGE_THRESHOLD = 12;
export const TIME_THRESHOLD_DAYS = 7;
export const TIME_THRESHOLD_MS = TIME_THRESHOLD_DAYS * 24 * 60 * 60 * 1000;
