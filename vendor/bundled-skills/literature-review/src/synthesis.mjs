import fs from 'node:fs/promises';
import { normalizeTopic } from './extraction.mjs';
import { validateSchema } from './validateSchema.mjs';

/**
 * Returns a weight for the given Truth Ladder type.
 */
export function getTypeWeight(type) {
  switch (type) {
    case 'OBSERVED':
      return 3;
    case 'CORROBORATED':
      return 2;
    case 'CLAIMED':
      return 1;
    case 'REFUTED':
      return 1;
    default:
      return 0;
  }
}

/**
 * Returns the Rung Multiplier for the given Truth Ladder type.
 */
export function getRungMultiplier(type) {
  switch (type) {
    case 'OBSERVED':
      return 1.0;
    case 'CORROBORATED':
      return 0.7;
    case 'CLAIMED':
      return 0.4;
    case 'REFUTED':
      return -1.0;
    default:
      return 0.0;
  }
}

/**
 * Calculates the consensus score for a single assumption claim.
 */
export function calculateConsensusScore(a) {
  const baseWeight = a.source?.citationCount !== undefined && a.source?.citationCount !== null ? a.source.citationCount : 0;
  const multiplier = getRungMultiplier(a.type);
  return baseWeight * multiplier;
}

/**
 * Resolves conflicts and corroborates assumptions across all candidates deterministically.
 */
const STOPWORDS = new Set([
  'the', 'a', 'an', 'is', 'are', 'was', 'be', 'being', 'been', 'of', 'to', 'about',
  'on', 'in', 'for', 'and', 'or', 'that', 'this', 'it', 'its', 'too', 'very', 'as',
  'by', 'at', 'not', 'no', 'but', 'with', 'should', 'must', 'need', 'needs', 'has',
  'have', 'plan', 'draft', 'there', 'here', 'we', 'you', 'under', 'over'
]);

const CONFLICT_IGNORE = new Set([
  'high', 'low', 'heavy', 'load', 'conflict', 'observed', 'claimed', 'corroborated', 'refuted',
  'good', 'bad', 'great', 'poor', 'large', 'small', 'much', 'little',
  'improvement', 'degrades', 'degrade', 'degraded', 'reach', 'reaches', 'reached',
  'faster', 'slower', 'better', 'worse',
  'the', 'a', 'an', 'is', 'are', 'was', 'be', 'being', 'been', 'of', 'to', 'about',
  'on', 'in', 'for', 'and', 'or', 'that', 'this', 'it', 'its', 'too', 'very', 'as',
  'by', 'at', 'not', 'no', 'but', 'with', 'should', 'must', 'need', 'needs', 'has',
  'have', 'plan', 'draft', 'there', 'here', 'we', 'you', 'under', 'over'
]);

function normalizeTopicForConflict(s) {
  const tokens = String(s ?? '').toLowerCase().match(/[a-z]+/g) || [];
  const kept = tokens.filter((t) => t.length > 1 && !CONFLICT_IGNORE.has(t));
  return (kept.length ? kept : tokens).sort().join('-');
}

export function resolveConflictsAndCorroborate(allAssumptions) {
  if (!allAssumptions || allAssumptions.length === 0) {
    return [];
  }

  // 1. Group assumptions by normalized topic of their statement
  const groups = new Map();
  for (const assumption of allAssumptions) {
    const topicKey = normalizeTopicForConflict(assumption.statement);
    if (!groups.has(topicKey)) {
      groups.set(topicKey, []);
    }
    groups.get(topicKey).push(assumption);
  }

  const synthesized = [];
  let index = 1;

  for (const [topicKey, group] of groups.entries()) {
    // 2. Sort group members to select the primary (winner)
    // Preference: Consensus Score (Base Weight * Rung Multiplier) desc -> Source Year desc -> PaperID asc
    group.sort((a, b) => {
      const scoreA = calculateConsensusScore(a);
      const scoreB = calculateConsensusScore(b);
      if (scoreA !== scoreB) {
        return scoreB - scoreA;
      }

      const yA = a.source?.year || 0;
      const yB = b.source?.year || 0;
      if (yA !== yB) return yB - yA;

      const idA = a.source?.entityId || '';
      const idB = b.source?.entityId || '';
      return idA.localeCompare(idB);
    });

    const primary = group[0];
    const secondaryList = group.slice(1);

    const corroborationSources = [];
    const conflicts = [];
    let hasCorroboratingPaper = false;

    // Use primary statement as base
    const primaryStatementLower = primary.statement.toLowerCase().trim();

    for (const other of secondaryList) {
      const otherStatementLower = other.statement.toLowerCase().trim();
      const otherSourceId = other.source?.entityId || other.source?.title || 'Unknown Source';

      // Check if it's corroboration or conflict
      if (otherStatementLower === primaryStatementLower) {
        corroborationSources.push(otherSourceId);
        if (other.source?.entityId && other.source.entityId !== primary.source?.entityId) {
          hasCorroboratingPaper = true;
        }
      } else {
        conflicts.push({
          statement: other.statement,
          sourceId: otherSourceId
        });
      }
    }

    // Determine type (upgrade to CORROBORATED if CLAIMED but has independent corroboration)
    let finalType = primary.type;
    if (finalType === 'CLAIMED' && (corroborationSources.length > 0 || hasCorroboratingPaper)) {
      finalType = 'CORROBORATED';
    }

    // Determine confidence
    let confidence = 0.5;
    if (finalType === 'OBSERVED') confidence = 0.9;
    else if (finalType === 'CORROBORATED') confidence = 0.7;
    else if (finalType === 'REFUTED') confidence = 0.8;

    // Adjust confidence based on corroboration and conflicts
    const uniqueCorrobCount = new Set(corroborationSources).size;
    confidence += uniqueCorrobCount * 0.05;
    confidence -= conflicts.length * 0.15;

    // Constraint check
    confidence = Math.max(0.10, Math.min(0.99, confidence));
    confidence = Math.round(confidence * 100) / 100;

    synthesized.push({
      id: `A${index++}`,
      statement: primary.statement,
      type: finalType,
      source: primary.source,
      confidence,
      consensusScore: calculateConsensusScore(primary),
      context: primary.context || `Resolved from topic: ${topicKey}`,
      corroborationSources: [...new Set(corroborationSources)],
      conflicts
    });
  }

  return synthesized;
}

/**
 * Fully populates the parameterized matrix.
 */
export function populateMatrix(candidates, columns) {
  const cols = Array.isArray(columns) ? columns : [];
  const rows = [];

  for (const cand of candidates) {
    const paperId = cand.paperId || cand.entityId || 'Unknown ID';
    const title = cand.title || 'Untitled';
    
    // Find if candidate already has an extracted matrix row
    const extractedRow = cand.matrix?.rows?.find(r => r.paperId === paperId) || cand.matrixRow || null;
    
    const values = {};
    for (const col of cols) {
      // Default to null, override with extracted value if present
      values[col] = extractedRow?.values?.[col] !== undefined ? extractedRow.values[col] : null;
    }

    rows.push({
      paperId,
      title,
      values
    });
  }

  return {
    columns: cols,
    rows
  };
}

/**
 * Generates a formatted Markdown report of the Assumptions Ledger.
 */
export function formatMarkdownLedger(ledger) {
  let md = `# Synthesized Assumptions Ledger\n\n`;
  md += `## Overview\n`;
  md += `- **Total Resolved Assumptions:** ${ledger.assumptions.length}\n`;
  
  const counts = { OBSERVED: 0, CORROBORATED: 0, CLAIMED: 0, REFUTED: 0 };
  let totalConflicts = 0;
  for (const a of ledger.assumptions) {
    counts[a.type] = (counts[a.type] || 0) + 1;
    totalConflicts += (a.conflicts || []).length;
  }
  
  md += `- **Observed (Factual):** ${counts.OBSERVED}\n`;
  md += `- **Corroborated:** ${counts.CORROBORATED}\n`;
  md += `- **Claimed (Hypothesized):** ${counts.CLAIMED}\n`;
  if (counts.REFUTED > 0) {
    md += `- **Refuted:** ${counts.REFUTED}\n`;
  }
  md += `- **Resolved Conflicts:** ${totalConflicts}\n\n`;

  md += `## Ledger Summary Table\n\n`;
  md += `| ID | Statement | Type | Confidence | Primary Source | Corroborators | Conflicts |\n`;
  md += `| --- | --- | --- | --- | --- | --- | --- |\n`;

  for (const a of ledger.assumptions) {
    const primarySource = a.source ? `${a.source.title} (${a.source.venue || 'No Venue'}, ${a.source.year || 'No Year'})` : 'N/A';
    const corrobText = (a.corroborationSources || []).join(', ') || '*None*';
    const conflictText = (a.conflicts || []).map(c => `${c.statement} (by ${c.sourceId})`).join('; ') || '*None*';
    
    md += `| **${a.id}** | ${a.statement} | \`${a.type}\` | ${a.confidence} | ${primarySource} | ${corrobText} | ${conflictText} |\n`;
  }

  md += `\n## Detailed Assumptions\n\n`;
  for (const a of ledger.assumptions) {
    md += `### ${a.id}: ${a.statement}\n`;
    md += `- **Type:** \`${a.type}\`\n`;
    md += `- **Confidence:** ${a.confidence}\n`;
    if (a.consensusScore !== undefined) {
      md += `- **Consensus Score:** ${a.consensusScore}\n`;
    }
    md += `- **Primary Source:** ${a.source?.title || 'Unknown'} (${a.source?.venue || 'N/A'}, ${a.source?.year || 'N/A'})\n`;
    if (a.context) {
      md += `- **Context:** ${a.context}\n`;
    }
    if (a.corroborationSources && a.corroborationSources.length > 0) {
      md += `- **Corroborated By:**\n`;
      for (const c of a.corroborationSources) {
        md += `  - ${c}\n`;
      }
    }
    if (a.conflicts && a.conflicts.length > 0) {
      md += `- **Conflicts:**\n`;
      for (const c of a.conflicts) {
        md += `  - **Contradiction:** "${c.statement}" (Source: ${c.sourceId})\n`;
      }
    }
    md += `\n---\n\n`;
  }

  return md;
}

/**
 * Runs the final synthesis and outputs results to disk.
 */
export async function runFinalSynthesis(candidates, columns, options = {}) {
  // 1. Gather all assumptions from all candidates
  const allAssumptions = [];
  for (const cand of candidates) {
    const ledger = cand.ledger || cand.assumptionsLedger || null;
    if (ledger?.assumptions) {
      for (const a of ledger.assumptions) {
        // Ensure source info is populated from candidate if missing
        if (!a.source) {
          a.source = {
            title: cand.title,
            authors: cand.authors || [],
            venue: cand.venue,
            year: cand.year,
            citationCount: cand.citationCount,
            entityId: cand.paperId || cand.entityId
          };
        }
        allAssumptions.push(a);
      }
    }
  }

  // 2. Resolve conflicts and cross-corroborate
  const synthesizedAssumptions = resolveConflictsAndCorroborate(allAssumptions);
  const ledger = { assumptions: synthesizedAssumptions };

  // 3. Fully populate Parameterized Matrix
  const matrix = populateMatrix(candidates, columns);

  // 4. Validate output schemas
  validateSchema(ledger, 'AssumptionsLedger');
  validateSchema(matrix, 'ParameterizedMatrix');

  // 5. Write to files
  if (options.ledgerJsonPath) {
    await fs.writeFile(options.ledgerJsonPath, JSON.stringify(ledger, null, 2), 'utf8');
  }

  if (options.matrixJsonPath) {
    await fs.writeFile(options.matrixJsonPath, JSON.stringify(matrix, null, 2), 'utf8');
  }

  const markdown = formatMarkdownLedger(ledger);
  if (options.ledgerMarkdownPath) {
    await fs.writeFile(options.ledgerMarkdownPath, markdown, 'utf8');
  }

  return {
    ledger,
    matrix,
    markdown
  };
}

/**
 * Weighted Consensus Aggregator for directional queries.
 */
export async function aggregateConsensus(assumptions, query, agent, options = {}) {
  const relevantAssumptions = [];
  
  // Stance extraction schema
  const STANCE_SCHEMA = {
    type: 'object',
    required: ['relevant', 'stance'],
    properties: {
      relevant: { type: 'boolean' },
      stance: { type: 'string', enum: ['supports', 'contradicts', 'neutral'] }
    }
  };

  for (const a of assumptions) {
    let classification = { relevant: false, stance: 'neutral' };

    if (options.mockStances && options.mockStances[a.statement] !== undefined) {
      classification = options.mockStances[a.statement];
    } else if (agent) {
      const prompt = [
        `You are the Weighted Consensus Aggregator for literature reviews.`,
        `Determine the relationship of the given assumption statement to the directional query.`,
        ``,
        `=== DIRECTIONAL QUERY ===`,
        query,
        ``,
        `=== ASSUMPTION STATEMENT ===`,
        a.statement,
        ``,
        `Your task is to classify whether the assumption is relevant to the query, and if so, whether it supports or contradicts the query.`,
        `Respond in JSON format matching this schema:`,
        `{`,
        `  "relevant": true/false,`,
        `  "stance": "supports" | "contradicts" | "neutral"`,
        `}`
      ].join('\n');

      try {
        const res = await agent(prompt, {
          label: 'aggregator:stance',
          schema: STANCE_SCHEMA,
          query,
          statement: a.statement
        });
        if (res && typeof res === 'object') {
          classification = res;
        } else {
          // If response is a string, try parsing it
          const parsed = JSON.parse(res);
          if (parsed && typeof parsed.relevant === 'boolean') {
            classification = parsed;
          }
        }
      } catch (err) {
        // Fallback on error
      }
    } else {
      // Deterministic heuristic if no agent or mock is provided: check keyword overlap
      const queryWords = query.toLowerCase().split(/\s+/).filter(w => w.length > 3);
      const statementLower = a.statement.toLowerCase();
      const hasOverlap = queryWords.some(w => statementLower.includes(w));
      if (hasOverlap) {
        let stance = 'neutral';
        if (statementLower.includes('improve') || statementLower.includes('increase') || statementLower.includes('higher') || statementLower.includes('faster')) {
          stance = 'supports';
        } else if (statementLower.includes('decrease') || statementLower.includes('lower') || statementLower.includes('reduce') || statementLower.includes('slower') || statementLower.includes('degrades')) {
          stance = 'contradicts';
        }
        classification = { relevant: true, stance };
      }
    }

    if (classification.relevant) {
      relevantAssumptions.push({
        assumption: a,
        stance: classification.stance
      });
    }
  }

  if (relevantAssumptions.length === 0) {
    return {
      score: 0,
      verdict: 'No Consensus',
      explanation: 'No relevant assumptions were found to address the directional query.',
      relevantCount: 0
    };
  }

  let weightedStanceSum = 0;
  let totalWeight = 0;
  
  for (const item of relevantAssumptions) {
    const weight = getTypeWeight(item.assumption.type);
    let stanceValue = 0;
    if (item.stance === 'supports') stanceValue = 1;
    else if (item.stance === 'contradicts') stanceValue = -1;

    weightedStanceSum += stanceValue * weight;
    totalWeight += weight;
  }

  const score = totalWeight > 0 ? weightedStanceSum / totalWeight : 0;
  
  let verdict = 'Neutral / Mixed';
  if (score >= 0.5) verdict = 'Strongly Supports';
  else if (score > 0.1) verdict = 'Weakly Supports';
  else if (score < -0.5) verdict = 'Strongly Contradicts';
  else if (score < -0.1) verdict = 'Weakly Contradicts';

  const explanation = `Based on ${relevantAssumptions.length} relevant assumptions (total weight: ${totalWeight}), the consensus score is ${score.toFixed(2)} (${verdict}).`;

  return {
    score,
    verdict,
    explanation,
    relevantCount: relevantAssumptions.length
  };
}
