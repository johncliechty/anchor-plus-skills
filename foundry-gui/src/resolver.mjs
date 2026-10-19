import path from 'node:path';

/**
 * Resolves a custom `foundry://` URI to a local filesystem path.
 * Supports:
 * - foundry://skills/coder -> <skillsDir>/coder/SKILL.md
 * - foundry://coder -> <skillsDir>/coder/SKILL.md
 * - foundry://coder/references/doc.md -> <skillsDir>/coder/references/doc.md
 * 
 * @param {string} uri The custom foundry:// URI.
 * @param {string} skillsDir The local skills directory.
 * @returns {string} The resolved absolute local filesystem path.
 */
export function resolveFoundryUri(uri, skillsDir) {
  if (typeof uri !== 'string' || !uri.startsWith('foundry://')) {
    throw new Error(`Invalid URI scheme: ${uri}. URIs must start with foundry://`);
  }
  
  let relativePath = uri.slice('foundry://'.length);
  
  // Normalize and remove leading/trailing slashes
  relativePath = relativePath.replace(/^\/+|\/+$/g, '');
  
  if (relativePath.startsWith('skills/')) {
    relativePath = relativePath.slice('skills/'.length).replace(/^\/+/g, '');
  }
  
  if (relativePath === '') {
    throw new Error('URI must specify a skill name or path');
  }
  
  const parts = relativePath.split('/');
  
  // If it's just a single segment, it represents a skill name, which resolves to <skill_name>/SKILL.md
  if (parts.length === 1) {
    return path.resolve(skillsDir, parts[0], 'SKILL.md');
  }
  
  return path.resolve(skillsDir, relativePath);
}
