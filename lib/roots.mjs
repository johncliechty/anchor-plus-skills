import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(__dirname, '..');

export function getConfigRoot() {
  if (process.env.ANCHOR_DATA_DIR) {
    return process.env.ANCHOR_DATA_DIR;
  }
  const platform = os.platform();
  if (platform === 'darwin') {
    return path.join(os.homedir(), 'Library', 'Application Support', 'Anchor');
  } else if (platform === 'win32') {
    return process.env.APPDATA ? path.join(process.env.APPDATA, 'Anchor') : path.join(os.homedir(), 'AppData', 'Roaming', 'Anchor');
  } else {
    return process.env.XDG_CONFIG_HOME ? path.join(process.env.XDG_CONFIG_HOME, 'anchor') : path.join(os.homedir(), '.config', 'anchor');
  }
}

export function getTrioRoot() {
  return process.env.TRIO_ROOT || path.resolve(REPO_ROOT, '..', 'trio');
}

export function getSkillFoundryRoot() {
  return process.env.SKILL_FOUNDRY_ROOT || path.resolve(REPO_ROOT, '..', 'Skill Foundry');
}

export function getTrioUrl(subPath) {
  return pathToFileURL(path.join(getTrioRoot(), subPath)).href;
}
