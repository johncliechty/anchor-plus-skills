/** W5: exactly three decision-record rules; the intake form is the refusal. */
import { brightHeartAsks, decisionValues, renderAsks } from './asks.brightheart.mjs';

export const OUTLINE_RULES = Object.freeze(['series.doctrine_tag', 'series.book_count', 'series.chapter_rule']);

export function outlineGate({ tuples = [], ledger, prose, commitReceipts } = {}) {
  const decisions = tuples.filter((t) => t.kind === 'decision');
  const values = Object.fromEntries(OUTLINE_RULES.map((id) => [id, decisionValues(decisions, id)]));
  const missing = OUTLINE_RULES.filter((id) => id === 'series.doctrine_tag' ? values[id].length === 0 : values[id].length !== 1);
  const asks = brightHeartAsks({ tuples, ledger, prose, commitReceipts });
  return { ok: missing.length === 0, refused: missing.length > 0, rules: OUTLINE_RULES, missing, values, asks,
    lines: [missing.length ? `Outline refused: missing or conflicting decision entries: ${missing.join(', ')}.` : 'Outline decision gate: ready.', ...renderAsks(asks)] };
}
