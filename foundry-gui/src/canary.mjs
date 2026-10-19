import fs from 'node:fs';
import path from 'node:path';

/**
 * Executes declarative canary tests against a proposed meta-recipe.
 */
export class CanaryRunner {
  /**
   * @param {string} canariesDir
   */
  constructor(canariesDir) {
    this.canariesDir = canariesDir;
  }

  /**
   * Validates the proposed metaRecipe against all declarative canary test suites in the canaries directory.
   * Throws an error if any canary test suite fails.
   * @param {object} metaRecipe
   * @returns {Promise<void>}
   */
  async validate(metaRecipe) {
    if (!metaRecipe || typeof metaRecipe !== 'object') {
      throw new Error('Proposed metaRecipe must be a non-null object');
    }

    if (!fs.existsSync(this.canariesDir)) {
      // If no canaries directory exists, verification passes vacuously
      return;
    }

    let files;
    try {
      files = fs.readdirSync(this.canariesDir);
    } catch (err) {
      throw new Error(`Failed to read canaries directory: ${err.message}`);
    }

    const jsonFiles = files.filter((f) => f.endsWith('.json'));

    for (const file of jsonFiles) {
      const filePath = path.join(this.canariesDir, file);
      let suite;
      try {
        const content = fs.readFileSync(filePath, 'utf8');
        suite = JSON.parse(content);
      } catch (err) {
        throw new Error(`Canary suite file "${file}" contains invalid JSON: ${err.message}`);
      }

      const suiteName = suite.name || file;
      const rules = suite.rules || [];

      if (!Array.isArray(rules)) {
        throw new Error(`Canary suite "${suiteName}" rules must be an array`);
      }

      for (let i = 0; i < rules.length; i++) {
        const rule = rules[i];
        const ruleDesc = rule.description || `rule ${i + 1}`;

        switch (rule.type) {
          case 'require_skill': {
            if (typeof rule.skill !== 'string') {
              throw new Error(`Canary suite "${suiteName}" require_skill rule must specify a string "skill"`);
            }
            const exists = metaRecipe.skills?.some((s) => s && s.name === rule.skill);
            if (!exists) {
              throw new Error(`Canary [${suiteName}] failed: Required skill "${rule.skill}" is missing (${ruleDesc})`);
            }
            break;
          }

          case 'recipe_contains': {
            if (typeof rule.skill !== 'string' || typeof rule.substring !== 'string') {
              throw new Error(`Canary suite "${suiteName}" recipe_contains rule must specify string "skill" and "substring"`);
            }
            const skill = metaRecipe.skills?.find((s) => s && s.name === rule.skill);
            if (!skill) {
              throw new Error(`Canary [${suiteName}] failed: Skill "${rule.skill}" not found for recipe check (${ruleDesc})`);
            }
            if (!skill.recipe || !skill.recipe.includes(rule.substring)) {
              throw new Error(`Canary [${suiteName}] failed: Skill "${rule.skill}" recipe does not contain "${rule.substring}" (${ruleDesc})`);
            }
            break;
          }

          case 'recipe_not_contains': {
            if (typeof rule.skill !== 'string' || typeof rule.substring !== 'string') {
              throw new Error(`Canary suite "${suiteName}" recipe_not_contains rule must specify string "skill" and "substring"`);
            }
            const skill = metaRecipe.skills?.find((s) => s && s.name === rule.skill);
            if (skill && skill.recipe && skill.recipe.includes(rule.substring)) {
              throw new Error(`Canary [${suiteName}] failed: Skill "${rule.skill}" recipe contains forbidden substring "${rule.substring}" (${ruleDesc})`);
            }
            break;
          }

          case 'recipe_matches': {
            if (typeof rule.skill !== 'string' || typeof rule.pattern !== 'string') {
              throw new Error(`Canary suite "${suiteName}" recipe_matches rule must specify string "skill" and "pattern"`);
            }
            const skill = metaRecipe.skills?.find((s) => s && s.name === rule.skill);
            if (!skill) {
              throw new Error(`Canary [${suiteName}] failed: Skill "${rule.skill}" not found for recipe regex check (${ruleDesc})`);
            }
            const flags = rule.flags || '';
            const regex = new RegExp(rule.pattern, flags);
            if (!skill.recipe || !regex.test(skill.recipe)) {
              throw new Error(`Canary [${suiteName}] failed: Skill "${rule.skill}" recipe does not match pattern /${rule.pattern}/ with flags "${flags}" (${ruleDesc})`);
            }
            break;
          }

          case 'system_prompt_contains': {
            if (typeof rule.substring !== 'string') {
              throw new Error(`Canary suite "${suiteName}" system_prompt_contains rule must specify string "substring"`);
            }
            const updates = metaRecipe.systemPromptUpdates || [];
            if (!Array.isArray(updates)) {
              throw new Error(`metaRecipe systemPromptUpdates must be an array`);
            }
            const contains = updates.some((u) => typeof u === 'string' && u.includes(rule.substring));
            if (!contains) {
              throw new Error(`Canary [${suiteName}] failed: systemPromptUpdates does not contain "${rule.substring}" (${ruleDesc})`);
            }
            break;
          }

          case 'system_prompt_not_contains': {
            if (typeof rule.substring !== 'string') {
              throw new Error(`Canary suite "${suiteName}" system_prompt_not_contains rule must specify string "substring"`);
            }
            const updates = metaRecipe.systemPromptUpdates || [];
            if (!Array.isArray(updates)) {
              throw new Error(`metaRecipe systemPromptUpdates must be an array`);
            }
            const contains = updates.some((u) => typeof u === 'string' && u.includes(rule.substring));
            if (contains) {
              throw new Error(`Canary [${suiteName}] failed: systemPromptUpdates contains forbidden substring "${rule.substring}" (${ruleDesc})`);
            }
            break;
          }

          default:
            throw new Error(`Unknown canary rule type: "${rule.type}" in suite "${suiteName}"`);
        }
      }
    }
  }
}
