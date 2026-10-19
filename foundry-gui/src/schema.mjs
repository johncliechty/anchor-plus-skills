import YAML from 'yaml';

export const AgentPayloadSchema = {
  $schema: "http://json-schema.org/draft-07/schema#",
  title: "AgentPayload",
  type: "object",
  properties: {
    timestamp: { type: "number" },
    version: { type: "string" },
    northStar: { type: "string" },
    summary: { type: "string" },
    metaRecipe: {
      type: "object",
      properties: {
        skills: {
          type: "array",
          items: {
            type: "object",
            properties: {
              name: { type: "string" },
              recipe: { type: "string" },
              changes: { type: "array", items: { type: "string" } }
            },
            required: ["name", "recipe"]
          }
        },
        systemPromptUpdates: { type: "array", items: { type: "string" } }
      },
      required: ["skills"]
    },
    timeline: {
      type: "array",
      items: {
        type: "object",
        properties: {
          timestamp: { type: "number" },
          event: { type: "string" },
          status: { type: "string", enum: ["success", "failure", "pending"] },
          details: { type: "string" }
        },
        required: ["timestamp", "event", "status"]
      }
    }
  },
  required: ["timestamp", "version", "northStar", "summary", "metaRecipe", "timeline"]
};

/**
 * Validates a payload object against the AgentPayloadSchema rules.
 * Throws an Error if validation fails.
 * @param {any} payload
 * @returns {boolean} true if valid
 */
export function validateAgentPayload(payload) {
  if (!payload || typeof payload !== 'object') {
    throw new Error('Payload must be a non-null object');
  }
  if (typeof payload.timestamp !== 'number') {
    throw new Error('Payload must have a numeric timestamp');
  }
  if (typeof payload.version !== 'string') {
    throw new Error('Payload must have a string version');
  }
  if (typeof payload.northStar !== 'string') {
    throw new Error('Payload must have a string northStar');
  }
  if (typeof payload.summary !== 'string') {
    throw new Error('Payload must have a string summary');
  }
  if (!payload.metaRecipe || typeof payload.metaRecipe !== 'object') {
    throw new Error('Payload must have a metaRecipe object');
  }
  if (!Array.isArray(payload.metaRecipe.skills)) {
    throw new Error('metaRecipe must have a skills array');
  }
  for (const skill of payload.metaRecipe.skills) {
    if (!skill || typeof skill !== 'object') {
      throw new Error('Every skill in metaRecipe must be an object');
    }
    if (typeof skill.name !== 'string') {
      throw new Error('Every skill must have a name');
    }
    if (typeof skill.recipe !== 'string') {
      throw new Error('Every skill must have a recipe');
    }
    if (skill.changes !== undefined && !Array.isArray(skill.changes)) {
      throw new Error('Skill changes must be an array of strings if provided');
    }
  }
  if (payload.metaRecipe.systemPromptUpdates !== undefined && !Array.isArray(payload.metaRecipe.systemPromptUpdates)) {
    throw new Error('systemPromptUpdates must be an array of strings if provided');
  }
  if (!Array.isArray(payload.timeline)) {
    throw new Error('Payload must have a timeline array');
  }
  for (const item of payload.timeline) {
    if (!item || typeof item !== 'object') {
      throw new Error('Every timeline item must be an object');
    }
    if (typeof item.timestamp !== 'number') {
      throw new Error('Every timeline item must have a timestamp');
    }
    if (typeof item.event !== 'string') {
      throw new Error('Every timeline item must have an event name');
    }
    if (!['success', 'failure', 'pending'].includes(item.status)) {
      throw new Error(`Invalid timeline item status: ${item.status}`);
    }
  }
  return true;
}

export const SkillSchema = {
  $schema: "http://json-schema.org/draft-07/schema#",
  title: "Skill",
  type: "object",
  properties: {
    frontmatter: {
      type: "object",
      properties: {
        name: { type: "string" },
        description: { type: "string" },
        dependencies: { type: "array", items: { type: "string" } }
      },
      required: ["name", "description"]
    },
    body: { type: "string" }
  },
  required: ["frontmatter", "body"]
};

/**
 * Validates a parsed skill object.
 * Throws an Error if validation fails.
 * @param {any} skill
 * @returns {boolean} true if valid
 */
export function validateSkill(skill) {
  if (!skill || typeof skill !== 'object') {
    throw new Error('Skill must be a non-null object');
  }
  if (!skill.frontmatter || typeof skill.frontmatter !== 'object') {
    throw new Error('Skill must have a frontmatter object');
  }
  if (typeof skill.frontmatter.name !== 'string' || skill.frontmatter.name.trim() === '') {
    throw new Error('Skill frontmatter must have a non-empty string name');
  }
  if (typeof skill.frontmatter.description !== 'string' || skill.frontmatter.description.trim() === '') {
    throw new Error('Skill frontmatter must have a non-empty string description');
  }
  if (skill.frontmatter.dependencies !== undefined) {
    if (!Array.isArray(skill.frontmatter.dependencies)) {
      throw new Error('Skill dependencies must be an array of strings');
    }
    for (const dep of skill.frontmatter.dependencies) {
      if (typeof dep !== 'string') {
        throw new Error('Skill dependencies must be strings');
      }
    }
  }
  if (typeof skill.body !== 'string') {
    throw new Error('Skill must have a string body');
  }
  return true;
}

/**
 * Parses and validates skill markdown content.
 * @param {string} content
 * @returns {object} parsed skill
 */
export function parseAndValidateSkill(content) {
  const match = content.match(/^---\r?\n([\s\S]+?)\r?\n---\r?\n([\s\S]*)/);
  if (!match) {
    throw new Error("Invalid skill format: Missing YAML frontmatter");
  }
  
  let frontmatter;
  try {
    frontmatter = YAML.parse(match[1]);
  } catch (err) {
    throw new Error(`Failed to parse YAML frontmatter: ${err.message}`);
  }
  
  const body = match[2];
  const skill = { frontmatter, body };
  validateSkill(skill);
  return skill;
}

