#!/usr/bin/env node
// Gandalf Executive Report Renderer — deterministic human-facing HTML & Markdown formatter.
//
// ANTI-LAUNDERING INVARIANTS (locked):
//   1. Deterministic from graded JSON only (zero post-grade LLM calls; never rewrites claims).
//   2. Translates earned stamps honestly — never drops certainty caveats:
//      • GROUNDED (cross_model:true) → "Cross-Family Verified (Independent Refuter Could Not Falsify)"
//      • PROMISING                   → "Single-Family Checked (Unverified Across Families)"
//      • SPECULATIVE                 → "Unverified Hypothesis (No Independent Refutation Ran)"
//      • Rungs (OBSERVED, CORROBORATED, CLAIMED, UNVERIFIED) → human-readable evidence pills.
//      • degraded:true or cross_model:false → prominent Scope & Verification Qualification callout.
//   3. Preserves kill_log in the human body under "Ideas Tested & Rejected by Adversarial Review".
//   4. Zero raw internal IDs (d-1, e-2, gcl1...) or JSON schema keys in executive prose; attaches
//      numbered footnote badges [1..N] mapped to a collapsed Verification & Machine Provenance Appendix.
//   5. Editorial warm-ivory / slate typography (>= 13px body & pills, print-to-PDF @media print).

import { readFileSync, writeFileSync, mkdirSync, realpathSync } from 'node:fs';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { basename, dirname, extname, join, resolve } from 'node:path';

const USAGE =
  'usage: node runtime/render-report.mjs --input <read.json> [--html <out.html>] [--md <out.md>] [--poincare-html <supp.html>] [--title "<title>"] [--subject "<subject>"] [--date "<date>"]';

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

function isNonEmptyString(v) {
  return typeof v === 'string' && v.trim() !== '';
}

/** Escape HTML special characters (XSS-safe). */
export function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Escape inline HTML tags in Markdown (`<script>`, `<skill>`, `<img ...>`) while keeping arrows (`<->`, `->`) readable. */
function escapeMdInline(value) {
  return String(value ?? '').replace(/<(?=[A-Za-z/!?])/g, '&lt;');
}

/** Translate earned elevation / leg tier honestly — never drops certainty caveats. */
export function translateTier(tier, { crossModel = false } = {}) {
  const t = String(tier || '').toUpperCase().trim();
  if (t === 'GROUNDED') {
    if (crossModel === true) {
      return 'Cross-Family Verified (Independent Refuter Could Not Falsify)';
    }
    return 'Single-Family Checked (Unverified Across Families)';
  }
  if (t === 'PROMISING') {
    return 'Single-Family Checked (Unverified Across Families)';
  }
  return 'Unverified Hypothesis (No Independent Refutation Ran)';
}

/** CSS modifier class for an earned tier pill. */
function tierClass(tier, { crossModel = false } = {}) {
  const t = String(tier || '').toUpperCase().trim();
  if (t === 'GROUNDED' && crossModel === true) return 'pill-tier-grounded';
  if (t === 'PROMISING' || (t === 'GROUNDED' && !crossModel)) return 'pill-tier-promising';
  return 'pill-tier-speculative';
}

/** Translate evidence rung into human-readable pill label. */
export function translateRung(rung) {
  const r = String(rung || '').toUpperCase().trim();
  switch (r) {
    case 'OBSERVED':
      return 'Observed Directly in Source';
    case 'CORROBORATED':
      return 'Corroborated';
    case 'CLAIMED':
      return 'Claimed (Needs Verification)';
    case 'UNVERIFIED':
      return 'Unverified Premortem';
    case 'REFUTED':
      return 'Refuted (Falsified)';
    default:
      return 'Unverified Premortem';
  }
}

function rungClass(rung) {
  const r = String(rung || '').toUpperCase().trim();
  switch (r) {
    case 'OBSERVED':
      return 'pill-rung-observed';
    case 'CORROBORATED':
      return 'pill-rung-corroborated';
    case 'CLAIMED':
      return 'pill-rung-claimed';
    case 'REFUTED':
      return 'pill-rung-refuted';
    default:
      return 'pill-rung-unverified';
  }
}

function translateSeverity(severity) {
  const s = String(severity || '').toLowerCase().trim();
  if (s === 'critical') return 'Critical Priority';
  if (s === 'major') return 'Major Priority';
  if (s === 'minor') return 'Minor Priority';
  return null;
}

function severityRank(severity) {
  const s = String(severity || '').toLowerCase().trim();
  if (s === 'critical') return 0;
  if (s === 'major') return 1;
  if (s === 'minor') return 2;
  return 3;
}

function severityClass(severity) {
  const s = String(severity || '').toLowerCase().trim();
  if (s === 'critical') return 'pill-sev-critical';
  if (s === 'major') return 'pill-sev-major';
  return 'pill-sev-minor';
}

function translateValueIfTrue(val) {
  const v = String(val || '').toLowerCase().trim();
  if (v === 'high') return 'High Potential Value';
  if (v === 'medium') return 'Medium Potential Value';
  if (v === 'low') return 'Modest Potential Value';
  return 'Potential Value Unspecified';
}

function translateLeg(leg) {
  const l = String(leg || '').toLowerCase().trim();
  if (l === 'diagnose') return 'Diagnosis';
  if (l === 'situate') return 'Best-in-Class Landscape';
  if (l === 'anticipate') return 'Coming Problems (Premortem)';
  return 'Assessment Dimension';
}

/** Detect bare machine IDs like d-1, e-2, s-1, a-1, n-1, f0, e-live, gcl1... */
function isRawInternalId(text) {
  if (!isNonEmptyString(text)) return true;
  const t = text.trim();
  if (t === '(untitled)') return true;
  return (
    /^[a-z]{1,4}-?\d+$/i.test(t) ||
    /^[deafns]-[a-z0-9_-]+$/i.test(t) ||
    /^gcl\d+\./i.test(t)
  );
}

/** Separate any host degradation footer tag (`[gandalf-host] ...`) from executive reasoning prose. */
function splitHostDegradationNote(rawReasoning) {
  const full = String(rawReasoning || '').trim();
  const marker = '[gandalf-host]';
  const idx = full.indexOf(marker);
  if (idx === -1) {
    return { narrative: full, hostNote: null };
  }
  const narrative = full.slice(0, idx).trim();
  const hostNote = full.slice(idx).trim();
  return {
    narrative: narrative || 'Assessment narrative ran under host conformance salvage.',
    hostNote,
  };
}

/** Deterministically split dense analytical prose into paragraphs without altering wording. */
function splitExecutiveParagraphs(text) {
  const rawBlocks = String(text || '')
    .split(/\r?\n\s*\r?\n+/)
    .map((b) => b.trim())
    .filter(Boolean);
  const paragraphs = [];
  for (const block of rawBlocks) {
    // Split inline numbered analytical points like "1. DEEP STRUCTURE: ... 4. ANCHOR.EXE SHELL: ..."
    const parts = block
      .split(/(?<=[.!?])\s+(?=\d+\.\s+[A-Z][A-Z0-9\s./&'()-]{2,}:)/)
      .map((p) => p.trim())
      .filter(Boolean);
    paragraphs.push(...parts);
  }
  return paragraphs.length > 0 ? paragraphs : [String(text || '').trim()];
}

/** Format a paragraph into HTML, bolding an ALL-CAPS numbered lead-in if present. */
function renderParagraphHtml(p) {
  const m = /^(\d+\.\s+[A-Z][A-Z0-9\s./&'()-]{2,}:)\s*([\s\S]*)$/.exec(p);
  if (m) {
    return `<p><strong>${escapeHtml(m[1])}</strong> ${escapeHtml(m[2])}</p>`;
  }
  return `<p>${escapeHtml(p)}</p>`;
}

/** Format a paragraph into Markdown, bolding an ALL-CAPS numbered lead-in if present. */
function renderParagraphMd(p) {
  const m = /^(\d+\.\s+[A-Z][A-Z0-9\s./&'()-]{2,}:)\s*([\s\S]*)$/.exec(p);
  if (m) {
    return `**${escapeMdInline(m[1])}** ${escapeMdInline(m[2])}`;
  }
  return escapeMdInline(p);
}

function validateGradedInput(gradedOutput) {
  if (!isPlainObject(gradedOutput)) {
    throw new Error('render-report: gradedOutput must be a plain object');
  }
  if (!isNonEmptyString(gradedOutput.reasoning)) {
    throw new Error("render-report: gradedOutput requires a non-empty 'reasoning' string");
  }
  if (!isNonEmptyString(gradedOutput.verdict)) {
    throw new Error("render-report: gradedOutput requires a non-empty 'verdict' string");
  }
}

/** Normalize graded JSON into ordered human-facing view model + numbered provenance footnotes [1..N]. */
function buildReportModel(gradedOutput, meta = {}) {
  validateGradedInput(gradedOutput);

  const crossModel = gradedOutput.cross_model === true;
  const crossModelRequested = gradedOutput.cross_model_requested === true;
  const degraded = gradedOutput.degraded === true;
  const scaledStamp = isNonEmptyString(gradedOutput.scaled_stamp) ? gradedOutput.scaled_stamp.trim() : null;
  const title = isNonEmptyString(meta.title) ? meta.title.trim() : 'Gandalf Executive Advisory Assessment';
  const subject = isNonEmptyString(meta.subject) ? meta.subject.trim() : null;
  const date = isNonEmptyString(meta.date) ? meta.date.trim() : null;

  const { narrative, hostNote } = splitHostDegradationNote(gradedOutput.reasoning);
  const narrativeParagraphs = splitExecutiveParagraphs(narrative);

  const rawFindings = Array.isArray(gradedOutput.findings) ? gradedOutput.findings.filter(isPlainObject) : [];
  const rawNitpicks = Array.isArray(gradedOutput.nitpicks) ? gradedOutput.nitpicks.filter(isPlainObject) : [];
  const rawElevations = Array.isArray(gradedOutput.elevations) ? gradedOutput.elevations.filter(isPlainObject) : [];
  const rawRiskLabels = Array.isArray(gradedOutput.risk_labels) ? gradedOutput.risk_labels.filter(isPlainObject) : [];

  const diagnoseRaw = rawFindings
    .filter((f) => !f.kind || f.kind === 'diagnose')
    .map((f, idx) => ({ f, idx }))
    .sort((a, b) => severityRank(a.f.severity) - severityRank(b.f.severity) || a.idx - b.idx)
    .map((x) => x.f);

  const nitpickFindings = [
    ...rawFindings.filter((f) => f.kind === 'nitpick'),
    ...rawNitpicks,
  ];
  const situateRaw = rawFindings.filter((f) => f.kind === 'situate');
  const anticipateRaw = rawFindings
    .filter((f) => f.kind === 'anticipate')
    .map((f, idx) => ({ f, idx }))
    .sort((a, b) => severityRank(a.f.severity) - severityRank(b.f.severity) || a.idx - b.idx)
    .map((x) => x.f);

  const killObj = isPlainObject(gradedOutput.kill_log) ? gradedOutput.kill_log : {};
  const killedElevationsRaw = Array.isArray(killObj.elevations) ? killObj.elevations.filter(isPlainObject) : [];
  const killedFindingsRaw = Array.isArray(killObj.findings) ? killObj.findings.filter(isPlainObject) : [];
  const killedNitpicksRaw = Array.isArray(killObj.nitpicks) ? killObj.nitpicks.filter(isPlainObject) : [];

  const footnotes = [];
  const mintFootnote = (entry) => {
    const num = footnotes.length + 1;
    footnotes.push({ num, ...entry });
    return num;
  };

  const diagnoseItems = diagnoseRaw.map((item, idx) => {
    const fn = mintFootnote({
      rawId: isNonEmptyString(item.id) ? item.id.trim() : `diagnose-${idx + 1}`,
      category: 'Diagnosis Finding',
      rawRung: item.rung || 'UNVERIFIED',
      rawTier: null,
      rawSeverity: item.severity || null,
      earnedLabel: translateRung(item.rung),
      protocol: item.gandalf_core?.protocol || null,
      degraded: item.degraded === true,
    });
    return {
      fn,
      severityLabel: translateSeverity(item.severity),
      severityCss: severityClass(item.severity),
      rungLabel: translateRung(item.rung),
      rungCss: rungClass(item.rung),
      verdict: String(item.verdict || '').trim(),
      reasoning: String(item.reasoning || '').trim(),
      degraded: item.degraded === true,
    };
  });

  const nitpickItems = nitpickFindings.map((item, idx) => {
    const fn = mintFootnote({
      rawId: isNonEmptyString(item.id) ? item.id.trim() : `nitpick-${idx + 1}`,
      category: 'Minor Observation',
      rawRung: item.rung || 'UNVERIFIED',
      rawTier: null,
      earnedLabel: translateRung(item.rung),
      degraded: item.degraded === true,
    });
    return {
      fn,
      rungLabel: translateRung(item.rung),
      rungCss: rungClass(item.rung),
      verdict: String(item.verdict || '').trim(),
      reasoning: String(item.reasoning || '').trim(),
    };
  });

  const situateItems = situateRaw.map((item, idx) => {
    const skeleton = item.s0_abstraction?.skeleton || item.abstraction?.skeleton || null;
    const structureAnswer = item.structure_map?.answer || null;
    const correspondences = Array.isArray(item.structure_map?.correspondences)
      ? item.structure_map.correspondences.filter(isPlainObject)
      : [];
    const factsVerified = item.facts_verified === true;
    const needsVerification = isNonEmptyString(item.needs_verification) ? item.needs_verification.trim() : null;
    const fn = mintFootnote({
      rawId: isNonEmptyString(item.id) ? item.id.trim() : `situate-${idx + 1}`,
      category: 'Landscape Framing',
      rawRung: item.rung || 'CLAIMED',
      rawTier: null,
      earnedLabel: translateRung(item.rung || 'CLAIMED'),
      commissionId: item.researchprime_commission_id || item.commission?.researchprime_commission_id || null,
      independentOrigin: item.independent_origin === true,
      factsVerified,
      needsVerification,
      degraded: item.degraded === true,
    });
    return {
      fn,
      rungLabel: translateRung(item.rung || 'CLAIMED'),
      rungCss: rungClass(item.rung || 'CLAIMED'),
      verdict: String(item.verdict || '').trim(),
      reasoning: String(item.reasoning || '').trim(),
      skeleton: isNonEmptyString(skeleton) ? skeleton.trim() : null,
      structureAnswer: isNonEmptyString(structureAnswer) ? structureAnswer.trim() : null,
      correspondences: correspondences.map((c) => ({
        source: String(c.source_relation || '').trim(),
        target: String(c.target_relation || '').trim(),
      })),
      outsideViewBaseRate: isNonEmptyString(item.outside_view_base_rate) ? item.outside_view_base_rate.trim() : null,
      unverifiedExternalComparison: !factsVerified || Boolean(needsVerification),
    };
  });

  const anticipateItems = anticipateRaw.map((item, idx) => {
    const fn = mintFootnote({
      rawId: isNonEmptyString(item.id) ? item.id.trim() : `anticipate-${idx + 1}`,
      category: 'Coming Problem (Premortem)',
      rawRung: item.rung || 'UNVERIFIED',
      rawTier: null,
      rawSeverity: item.severity || null,
      earnedLabel: translateRung(item.rung || 'UNVERIFIED'),
      subjectCardinality: item.subject_cardinality ?? 1,
      degraded: item.degraded === true,
    });
    return {
      fn,
      severityLabel: translateSeverity(item.severity),
      severityCss: severityClass(item.severity),
      rungLabel: translateRung(item.rung || 'UNVERIFIED'),
      rungCss: rungClass(item.rung || 'UNVERIFIED'),
      verdict: String(item.verdict || '').trim(),
      reasoning: String(item.reasoning || '').trim(),
      futureCondition: isNonEmptyString(item.future_state_condition) ? item.future_state_condition.trim() : null,
      enablingAssumption: isNonEmptyString(item.enabling_assumption) ? item.enabling_assumption.trim() : null,
    };
  });

  const elevationItems = rawElevations.map((item, idx) => {
    const prov = isPlainObject(item.refutation_provenance) ? item.refutation_provenance : null;
    const effectiveCross = crossModel && item.cross_family_refuted !== false;
    const tierLabel = translateTier(item.tier, { crossModel: effectiveCross });
    const whatWouldRefuteIt = isNonEmptyString(item.what_would_refute_it) ? item.what_would_refute_it.trim() : null;
    const fn = mintFootnote({
      rawId: isNonEmptyString(item.id) ? item.id.trim() : `elevation-${idx + 1}`,
      category: 'Recommended Elevation',
      rawRung: item.rung || null,
      rawTier: item.tier || 'SPECULATIVE',
      rawValueIfTrue: item.value_if_true || null,
      rawSeverity: item.severity || null,
      earnedLabel: tierLabel,
      whatWouldRefuteIt,
      drafterFamily: prov?.drafter_family || null,
      refuterFamily: prov?.refuter_family || null,
      survived: typeof prov?.survived === 'boolean' ? prov.survived : null,
      resultDigest: prov?.result_digest || null,
      commissionId: prov?.refuter_commission_id || prov?.commission_id || null,
      refuterDefeater: isNonEmptyString(prov?.defeater) ? prov.defeater.trim() : null,
      refuterVerdict: isNonEmptyString(prov?.verdict) ? prov.verdict.trim() : null,
      refutationStamp: isNonEmptyString(item.refutation_stamp) ? item.refutation_stamp.trim() : null,
      degraded: item.degraded === true,
    });
    return {
      fn,
      tierLabel,
      tierCss: tierClass(item.tier, { crossModel: effectiveCross }),
      valueLabel: translateValueIfTrue(item.value_if_true),
      rungLabel: item.rung ? translateRung(item.rung) : null,
      rungCss: item.rung ? rungClass(item.rung) : 'pill-rung-unverified',
      verdict: String(item.verdict || '').trim(),
      reasoning: String(item.reasoning || '').trim(),
      falsificationTest: whatWouldRefuteIt,
      reviewerVerdictNote: isNonEmptyString(prov?.verdict) ? prov.verdict.trim() : null,
    };
  });

  const rejectedItems = [];
  const pushRejected = (rawList, kindLabel, fallbackPrefix) => {
    rawList.forEach((k, idx) => {
      const brief = isNonEmptyString(k.brief) ? k.brief.trim() : '';
      const rawId = brief || `${fallbackPrefix}-${k.index ?? idx}`;
      const humanTitle = isRawInternalId(brief)
        ? `Rejected Candidate ${kindLabel} #${idx + 1}`
        : brief;
      const defeaterText = isNonEmptyString(k.defeater)
        ? k.defeater.trim()
        : 'Rejected after failing its named falsification check during grading.';
      const rawReason = isNonEmptyString(k.reason) ? k.reason.trim() : 'REFUTED';
      const statusLabel = /refuted/i.test(rawReason)
        ? 'Rejected — Falsified in Adversarial Review'
        : 'Dropped During Conformance Check';
      const fn = mintFootnote({
        rawId,
        category: `Rejected ${kindLabel}`,
        rawRung: /refuted/i.test(rawReason) ? 'REFUTED' : null,
        rawTier: 'REFUTED',
        earnedLabel: statusLabel,
        killIndex: typeof k.index === 'number' ? k.index : idx,
        killReason: rawReason,
        refuterDefeater: isNonEmptyString(k.defeater) ? k.defeater.trim() : null,
      });
      rejectedItems.push({
        fn,
        humanTitle,
        kindLabel,
        statusLabel,
        defeaterText,
      });
    });
  };
  pushRejected(killedElevationsRaw, 'Proposal', 'killed-elevation');
  pushRejected(killedFindingsRaw, 'Finding', 'killed-finding');
  pushRejected(killedNitpicksRaw, 'Observation', 'killed-nitpick');

  const dimensionSummaries = rawRiskLabels.map((rl) => ({
    dimension: translateLeg(rl.leg),
    tierLabel: translateTier(rl.tier, { crossModel }),
    rungLabel: rl.rung ? translateRung(rl.rung) : null,
    rungCss: rl.rung ? rungClass(rl.rung) : 'pill-rung-unverified',
  }));

  // Build plain-English Scope & Verification Qualification callout when degraded or single-family.
  const qualificationReasons = [];
  if (degraded) {
    qualificationReasons.push(
      'One or more parts of this assessment ran in degraded mode (for example, salvaged to a validated subset or completed without an external verification pass). Treat unverified comparisons and premortem items conservatively.'
    );
  }
  if (!crossModel) {
    qualificationReasons.push(
      'No cross-family adversarial refuter verified this run. All findings and recommendations reflect a single-family or deterministic grading pass and cannot reach Cross-Family Verified status until stress-tested by an independent model family.'
    );
  }
  if (scaledStamp) {
    qualificationReasons.push(`Scaled codebase analysis note: ${scaledStamp}`);
  }

  return {
    title,
    subject,
    date,
    supplementHref: isNonEmptyString(meta.supplementHref) ? meta.supplementHref.trim() : null,
    reportBackHref: isNonEmptyString(meta.reportBackHref) ? meta.reportBackHref.trim() : null,
    schemaVersion: String(gradedOutput.schema_version || 'gandalf-advisor-1'),
    crossModel,
    crossModelRequested,
    degraded,
    scaledStamp,
    hostNote,
    qualificationNeeded: degraded || !crossModel,
    qualificationReasons,
    verdict: String(gradedOutput.verdict || '').trim(),
    isSoundVerdict: String(gradedOutput.verdict || '').trim().toLowerCase() === 'this is sound',
    narrativeParagraphs,
    dimensionSummaries,
    diagnoseItems,
    nitpickItems,
    situateItems,
    anticipateItems,
    elevationItems,
    rejectedItems,
    footnotes,
  };
}

/**
 * Deterministic Sarkar + Radial Importance Promotion + Isometric Möbius Gyrovector
 * Poincaré Knowledge & Risk State Map builder over the sanitized report model `m`.
 * Zero LLM calls, zero raw internal IDs, 100% deterministic float64 coordinates.
 */
function buildPoincareKnowledgeMap(m) {
  const TAU = 1.28;
  const ALPHA = 0.55;
  const SCALE = 3.1;

  const rawNodes = [
    {
      key: 'origin',
      parentKey: null,
      fn: null,
      shell: 'Core Origin',
      color: '#B45309',
      importance: 1.0,
      boneyard: false,
      label: truncateWords(m.verdict || 'Central Verdict', 58),
      posture: m.crossModel ? 'Cross-Family Reviewed' : 'Executive Verdict',
    },
  ];

  const sectors = [
    {
      key: 'sec-diagnose',
      label: 'Diagnosis Sector',
      color: '#B91C1C',
      importance: 0.93,
      boneyard: false,
      items: [
        ...m.diagnoseItems.map((d) => ({
          fn: d.fn,
          label: truncateWords(d.verdict, 54),
          importance: d.severityLabel && d.severityLabel.includes('Critical') ? 0.96 : 0.87,
          posture: [d.severityLabel, d.rungLabel].filter(Boolean).join(' · '),
          color: '#DC2626',
          boneyard: false,
        })),
        ...m.nitpickItems.map((n) => ({
          fn: n.fn,
          label: truncateWords(n.verdict, 50),
          importance: 0.70,
          posture: n.rungLabel || 'Minor Observation',
          color: '#64748B',
          boneyard: false,
        })),
      ],
    },
    {
      key: 'sec-situate',
      label: 'Landscape Framing',
      color: '#6D28D9',
      importance: 0.90,
      boneyard: false,
      items: m.situateItems.map((s) => ({
        fn: s.fn,
        label: truncateWords(s.verdict, 54),
        importance: 0.88,
        posture: s.rungLabel || 'Landscape Situate',
        color: '#7C3AED',
        boneyard: false,
      })),
    },
    {
      key: 'sec-elevate',
      label: 'Recommended Elevations',
      color: '#047857',
      importance: 0.94,
      boneyard: false,
      items: m.elevationItems.map((e) => ({
        fn: e.fn,
        label: truncateWords(e.verdict, 54),
        importance: e.tierLabel && e.tierLabel.includes('Cross-Family Verified')
          ? 0.97
          : e.tierLabel && e.tierLabel.includes('Single-Family')
            ? 0.86
            : 0.68,
        posture: e.tierLabel || 'Elevation',
        color: '#059669',
        boneyard: false,
      })),
    },
    {
      key: 'sec-anticipate',
      label: 'Premortem Horizon',
      color: '#C2410C',
      importance: 0.88,
      boneyard: false,
      items: m.anticipateItems.map((a) => ({
        fn: a.fn,
        label: truncateWords(a.verdict, 54),
        importance: 0.85,
        posture: [a.severityLabel, a.rungLabel].filter(Boolean).join(' · '),
        color: '#EA580C',
        boneyard: false,
      })),
    },
    {
      key: 'sec-rejected',
      label: 'Refuted Boneyard',
      color: '#64748B',
      importance: 0.48,
      boneyard: false,
      items: m.rejectedItems.map((r) => ({
        fn: r.fn,
        label: truncateWords(r.humanTitle, 52),
        importance: 0.30,
        posture: r.statusLabel || 'Rejected in Review',
        color: '#991B1B',
        boneyard: true,
      })),
    },
  ];

  const activeSectors = sectors.filter((s) => s.items.length > 0);
  const totalWeight = activeSectors.reduce((acc, s) => acc + s.items.length + 0.5, 0) || 1;
  let curAngle = -Math.PI / 2;

  for (const sec of activeSectors) {
    const w = sec.items.length + 0.5;
    const span = (2 * Math.PI * w) / totalWeight;
    const secTheta = curAngle + 0.5 * span;
    const secRTree = TAU * 0.72;
    const secREff = Math.max(0.28, secRTree * (1 - ALPHA * sec.importance * sec.importance));
    rawNodes.push({
      key: sec.key,
      parentKey: 'origin',
      fn: null,
      shell: 'Sector Hub',
      color: sec.color,
      importance: sec.importance,
      boneyard: false,
      rTree: secRTree,
      rEff: secREff,
      theta: secTheta,
      label: sec.label,
      posture: `${sec.items.length} Node${sec.items.length === 1 ? '' : 's'}`,
    });

    const nItems = sec.items.length;
    sec.items.forEach((it, idx) => {
      const itemTheta = curAngle + ((idx + 0.5) * span) / Math.max(1, nItems);
      const rTree = secRTree + TAU;
      const rEff = it.boneyard
        ? 3.85
        : Math.max(0.42, rTree * (1 - ALPHA * it.importance * it.importance));
      const shell = it.boneyard
        ? 'Outer Refuted Boneyard'
        : rEff < 1.25
          ? 'Inner Verified / Critical Shell'
          : 'Mid Horizon Shell';
      rawNodes.push({
        key: `${sec.key}-${idx + 1}`,
        parentKey: sec.key,
        fn: it.fn,
        shell,
        color: it.color,
        importance: it.importance,
        boneyard: it.boneyard,
        rTree,
        rEff,
        theta: itemTheta,
        label: it.label,
        posture: it.posture,
      });
    });

    curAngle += span;
  }

  rawNodes[0].rTree = 0;
  rawNodes[0].rEff = 0;
  rawNodes[0].theta = 0;

  for (const nd of rawNodes) {
    const rho = Math.min(0.94, Math.tanh(nd.rEff / SCALE));
    nd.zx = rho * Math.cos(nd.theta);
    nd.zy = rho * Math.sin(nd.theta);
  }

  return { nodes: rawNodes, activeSectors };
}

function truncateWords(str, maxLen) {
  const clean = String(str || '').replace(/\s+/g, ' ').trim();
  if (clean.length <= maxLen) return clean;
  return clean.slice(0, Math.max(1, maxLen - 1)).trimEnd() + '…';
}

function mobiusTranslateDisk(zx, zy, fx, fy) {
  const nr = zx - fx;
  const ni = zy - fy;
  const dr = 1 - (fx * zx + fy * zy);
  const di = -(fx * zy - fy * zx);
  const den = dr * dr + di * di;
  if (den < 1e-12) return [0, 0];
  let ox = (nr * dr + ni * di) / den;
  let oy = (ni * dr - nr * di) / den;
  const mag = Math.hypot(ox, oy);
  if (mag > 0.955) {
    ox *= 0.955 / mag;
    oy *= 0.955 / mag;
  }
  return [ox, oy];
}

function poincareGeodesicSvgD(x1, y1, x2, y2) {
  const cross = x1 * y2 - y1 * x2;
  const seg = Math.hypot(x2 - x1, y2 - y1);
  if (Math.abs(cross) < 1e-3 || seg < 0.03) {
    return `M ${x1.toFixed(4)} ${y1.toFixed(4)} L ${x2.toFixed(4)} ${y2.toFixed(4)}`;
  }
  const r1sq = 0.5 * (x1 * x1 + y1 * y1 + 1);
  const r2sq = 0.5 * (x2 * x2 + y2 * y2 + 1);
  const cx = (r1sq * y2 - r2sq * y1) / cross;
  const cy = (x1 * r2sq - x2 * r1sq) / cross;
  const R = Math.sqrt(Math.max(0.0001, cx * cx + cy * cy - 1));
  if (!Number.isFinite(R) || R > 25) {
    return `M ${x1.toFixed(4)} ${y1.toFixed(4)} L ${x2.toFixed(4)} ${y2.toFixed(4)}`;
  }
  const sweep = cross > 0 ? 0 : 1;
  return `M ${x1.toFixed(4)} ${y1.toFixed(4)} A ${R.toFixed(4)} ${R.toFixed(4)} 0 0 ${sweep} ${x2.toFixed(4)} ${y2.toFixed(4)}`;
}

function renderPoincareSvgLayer(nodes, focusNode) {
  const [fx, fy] = focusNode ? [focusNode.zx, focusNode.zy] : [0, 0];
  const coords = {};
  for (const nd of nodes) {
    coords[nd.key] = mobiusTranslateDisk(nd.zx, nd.zy, fx, fy);
  }
  const svg = [];
  svg.push(
    '<svg class="gpm-disk-svg" viewBox="-1.08 -1.08 2.16 2.16" role="img" aria-label="Poincaré Knowledge and Risk Disk">'
  );
  svg.push('  <circle cx="0" cy="0" r="1.0" fill="#0B1324" stroke="#334155" stroke-width="0.012"/>');
  svg.push('  <circle cx="0" cy="0" r="0.38" fill="none" stroke="#1E3A8A" stroke-width="0.005" stroke-dasharray="0.016,0.016"/>');
  svg.push('  <circle cx="0" cy="0" r="0.72" fill="none" stroke="#1E3A8A" stroke-width="0.005" stroke-dasharray="0.016,0.016"/>');
  svg.push('  <circle cx="0" cy="0" r="0.90" fill="none" stroke="#7F1D1D" stroke-width="0.005" stroke-dasharray="0.02,0.02"/>');

  for (const nd of nodes) {
    if (!nd.parentKey || !coords[nd.parentKey] || !coords[nd.key]) continue;
    const [x1, y1] = coords[nd.parentKey];
    const [x2, y2] = coords[nd.key];
    const stroke = nd.boneyard ? 'rgba(248,113,113,0.34)' : 'rgba(125,211,252,0.42)';
    svg.push(
      `  <path d="${poincareGeodesicSvgD(x1, y1, x2, y2)}" fill="none" stroke="${stroke}" stroke-width="0.006"/>`
    );
  }

  const ordered = nodes.slice().sort((a, b) => {
    const da = Math.hypot(...coords[a.key]);
    const db = Math.hypot(...coords[b.key]);
    return db - da;
  });

  for (const nd of ordered) {
    const [x, y] = coords[nd.key];
    const r2 = Math.min(0.95, x * x + y * y);
    const conformal = Math.pow(1 - r2, 0.48);
    const baseR = nd.key === 'origin' ? 0.062 : nd.fn ? 0.044 : 0.048;
    const rad = Math.max(0.018, baseR * conformal);
    const isFocus = focusNode && nd.key === focusNode.key;
    const ring = isFocus
      ? `<circle cx="${x.toFixed(4)}" cy="${y.toFixed(4)}" r="${(rad + 0.022).toFixed(4)}" fill="none" stroke="#FDE68A" stroke-width="0.008"/>`
      : '';
    const badgeTxt = nd.fn ? `[${nd.fn}]` : nd.key === 'origin' ? '★' : '●';
    const shortTxt = !nd.fn && Math.sqrt(r2) < 0.65 ? escapeHtml(nd.label) : '';
    const inner =
      `${ring}` +
      `<circle cx="${x.toFixed(4)}" cy="${y.toFixed(4)}" r="${rad.toFixed(4)}" fill="${nd.color}" stroke="#F8FAFC" stroke-width="0.005">` +
      `<title>${escapeHtml(nd.label)} — ${escapeHtml(nd.posture)} (r_eff=${nd.rEff.toFixed(2)})</title>` +
      `</circle>` +
      `<text x="${x.toFixed(4)}" y="${(y + 0.013).toFixed(4)}" text-anchor="middle" fill="#FFFFFF" font-size="0.036" font-weight="700">${escapeHtml(badgeTxt)}</text>` +
      (shortTxt
        ? `<text x="${x.toFixed(4)}" y="${(y - rad - 0.016).toFixed(4)}" text-anchor="middle" fill="#E2E8F0" font-size="0.034" font-weight="600">${shortTxt}</text>`
        : '');
    if (nd.fn) {
      svg.push(`  <a href="#provref-${nd.fn}">${inner}</a>`);
    } else {
      svg.push(`  <g>${inner}</g>`);
    }
  }
  svg.push('</svg>');
  return svg.join('\n');
}

/**
 * Deterministically render a graded Gandalf JSON object into an executive Markdown report.
 * Zero post-grade LLM calls; preserves all uncertainty caveats and kill_log entries.
 */
export function renderExecutiveMarkdown(gradedOutput, meta = {}) {
  const m = buildReportModel(gradedOutput, meta);
  const lines = [];

  lines.push(`# ${escapeMdInline(m.title)}`);
  const metaParts = [
    m.crossModel
      ? '**Verification Posture:** Cross-Family Adversarial Review Completed'
      : '**Verification Posture:** Single-Family / Deterministic Pass (Unverified Across Families)',
  ];
  if (m.degraded) metaParts.push('**Run Health:** Degraded Scope (See Qualification Below)');
  if (m.subject) metaParts.unshift(`**Subject:** ${escapeMdInline(m.subject)}`);
  if (m.date) metaParts.push(`**Date:** ${escapeMdInline(m.date)}`);
  lines.push(metaParts.join(' · '));
  lines.push('');

  if (m.qualificationNeeded) {
    lines.push('> **Scope & Verification Qualification**');
    for (const reason of m.qualificationReasons) {
      lines.push(`> - ${escapeMdInline(reason)}`);
    }
    lines.push('');
  }

  // 1. Executive Summary & Verdict
  lines.push('## Executive Summary & Verdict');
  lines.push('');
  lines.push(`> **Bottom-Line Verdict:** ${escapeMdInline(m.verdict)}`);
  lines.push('');
  if (m.dimensionSummaries.length > 0) {
    lines.push(
      '**Evidence & Verification Posture by Dimension:** ' +
        m.dimensionSummaries
          .map((d) => `*${d.dimension}:* ${d.rungLabel || d.tierLabel}`)
          .join(' · ')
    );
    lines.push('');
  }
  lines.push('### Core Analytical Synthesis');
  lines.push('');
  for (const p of m.narrativeParagraphs) {
    lines.push(renderParagraphMd(p));
    lines.push('');
  }

  // 1b. Poincaré Knowledge & Risk State Map (Hyperbolic Shell Projection)
  const pmapMd = buildPoincareKnowledgeMap(m);
  if (pmapMd.nodes.length > 1) {
    lines.push('## Poincaré Knowledge & Risk State Map');
    lines.push('');
    if (m.supplementHref) {
      lines.push(
        `> **Interactive Gandalf Poincaré Map Supplement:** Open [\`${escapeMdInline(m.supplementHref)}\`](${m.supplementHref}) to click any finding, elevation, or premortem node and Möbius-zoom the hyperbolic risk map interactively.`
      );
      lines.push('');
    }
    lines.push(
      'Hyperbolic Sarkar + Radial Importance Promotion layout placing the central verdict at the origin `(0, 0)`, radially promoting high-importance verified findings and elevations inward, and receding refuted candidates to the outer Boneyard horocycle:'
    );
    lines.push('');
    lines.push('| Hyperbolic Shell | Claim / Sector | Ref | Effective Radius | Posture |');
    lines.push('| :--- | :--- | :--- | :--- | :--- |');
    for (const nd of pmapMd.nodes) {
      if (nd.shell === 'Sector Hub') continue;
      const refCol = nd.fn ? `[${nd.fn}]` : 'Origin';
      lines.push(
        `| ${escapeMdInline(nd.shell).replace(/\|/g, '\\|')} | ${escapeMdInline(nd.label).replace(/\|/g, '\\|')} | ${refCol} | ${nd.rEff.toFixed(2)} | ${escapeMdInline(nd.posture).replace(/\|/g, '\\|')} |`
      );
    }
    lines.push('');
  }

  // 2. What Is Really Going On (Ranked Diagnosis)
  lines.push('## What Is Really Going On (Ranked Diagnosis)');
  lines.push('');
  if (m.diagnoseItems.length === 0) {
    lines.push(
      m.isSoundVerdict
        ? 'No structural defects were identified; the assessed artifact is sound.'
        : 'No separate structural diagnosis items were recorded beyond the executive synthesis above.'
    );
    lines.push('');
  } else {
    m.diagnoseItems.forEach((d, idx) => {
      const pills = [d.severityLabel, d.rungLabel].filter(Boolean).join(' · ');
      lines.push(`### ${idx + 1}. ${escapeMdInline(d.verdict)} [${d.fn}]`);
      lines.push(`*${pills}*`);
      lines.push('');
      lines.push(escapeMdInline(d.reasoning));
      lines.push('');
    });
  }

  if (m.nitpickItems.length > 0) {
    lines.push('### Additional Polish & Minor Observations');
    lines.push('');
    for (const n of m.nitpickItems) {
      lines.push(`- **${escapeMdInline(n.verdict)}** *(${n.rungLabel})* [${n.fn}] — ${escapeMdInline(n.reasoning)}`);
    }
    lines.push('');
  }

  // 3. Best-in-Class Landscape Framing
  if (m.situateItems.length > 0) {
    lines.push('## Best-in-Class Landscape Framing');
    lines.push('');
    for (const s of m.situateItems) {
      lines.push(`### ${escapeMdInline(s.verdict)} [${s.fn}]`);
      lines.push(`*${s.rungLabel}*`);
      lines.push('');
      lines.push(escapeMdInline(s.reasoning));
      lines.push('');
      if (s.skeleton) {
        lines.push(`- **Underlying Structural Challenge:** ${escapeMdInline(s.skeleton)}`);
      }
      if (s.structureAnswer) {
        lines.push(`- **Reference Architecture Pattern:** ${escapeMdInline(s.structureAnswer)}`);
      }
      if (s.outsideViewBaseRate) {
        lines.push(`- **Outside-View Base Rate:** ${escapeMdInline(s.outsideViewBaseRate)}`);
      }
      if (s.correspondences.length > 0) {
        lines.push('');
        lines.push('| Proven Pattern in Reference Field | Application to This Effort |');
        lines.push('| :--- | :--- |');
        for (const c of s.correspondences) {
          lines.push(
            `| ${escapeMdInline(c.source).replace(/\|/g, '\\|')} | ${escapeMdInline(c.target).replace(/\|/g, '\\|')} |`
          );
        }
      }
      if (s.unverifiedExternalComparison) {
        lines.push('');
        lines.push(
          '> *Verification Caveat:* External reference patterns and base-rate comparisons above have not yet been independently verified by a dedicated research pass and remain Claimed (Needs Verification).'
        );
      }
      lines.push('');
    }
  }

  // 4. Coming Problems (Premortem)
  if (m.anticipateItems.length > 0) {
    lines.push('## Coming Problems (Premortem)');
    lines.push('');
    m.anticipateItems.forEach((a, idx) => {
      const pills = [a.severityLabel, a.rungLabel].filter(Boolean).join(' · ');
      lines.push(`### ${idx + 1}. ${escapeMdInline(a.verdict)} [${a.fn}]`);
      lines.push(`*${pills}*`);
      lines.push('');
      if (a.futureCondition) {
        lines.push(`- **Coming Failure Mode:** ${escapeMdInline(a.futureCondition)}`);
      }
      if (a.enablingAssumption) {
        lines.push(`- **Enabling Assumption:** ${escapeMdInline(a.enablingAssumption)}`);
      }
      lines.push('');
      lines.push(escapeMdInline(a.reasoning));
      lines.push('');
    });
  }

  // 5. Recommended Elevations
  lines.push('## Recommended Elevations');
  lines.push('');
  if (m.elevationItems.length === 0) {
    lines.push('No forward elevations survived or were proposed on this pass.');
    lines.push('');
  } else {
    m.elevationItems.forEach((e, idx) => {
      const pills = [e.tierLabel, e.valueLabel, e.rungLabel].filter(Boolean).join(' · ');
      lines.push(`### ${idx + 1}. ${escapeMdInline(e.verdict)} [${e.fn}]`);
      lines.push(`*${pills}*`);
      lines.push('');
      lines.push(escapeMdInline(e.reasoning));
      lines.push('');
      if (e.falsificationTest) {
        lines.push(`- **Falsification Test (How we'd know this is wrong):** ${escapeMdInline(e.falsificationTest)}`);
      }
      if (e.reviewerVerdictNote) {
        lines.push(`- **Independent Reviewer Assessment & Boundary Conditions:** ${escapeMdInline(e.reviewerVerdictNote)}`);
      }
      lines.push('');
    });
  }

  // 6. Ideas Tested & Rejected by Adversarial Review
  if (m.rejectedItems.length > 0) {
    lines.push('## Ideas Tested & Rejected by Adversarial Review');
    lines.push('');
    lines.push(
      'The following candidate proposals or claims were stress-tested against concrete falsification checks and rejected when the named defeater held up:'
    );
    lines.push('');
    for (const r of m.rejectedItems) {
      lines.push(`### ${escapeMdInline(r.humanTitle)} [${r.fn}]`);
      lines.push(`*${r.statusLabel}*`);
      lines.push('');
      lines.push(`**Concrete Defeater That Falsified It:** ${escapeMdInline(r.defeaterText)}`);
      lines.push('');
    }
  }

  // 7. Collapsed Verification & Machine Provenance Appendix
  lines.push('<details>');
  lines.push(`<summary>Verification &amp; Machine Provenance Appendix (${m.footnotes.length} Footnotes)</summary>`);
  lines.push('');
  lines.push(
    `- **Schema:** \`${escapeMdInline(m.schemaVersion)}\` · \`cross_model=${m.crossModel}\` · \`cross_model_requested=${m.crossModelRequested}\` · \`degraded=${m.degraded}\``
  );
  if (m.hostNote) {
    lines.push(`- **Host Conformance Note:** \`${escapeMdInline(m.hostNote)}\``);
  }
  lines.push('');
  for (const fn of m.footnotes) {
    lines.push(`- **[${fn.num}] → \`${escapeMdInline(fn.rawId)}\`** (${escapeMdInline(fn.category)})`);
    const metaBits = [];
    if (fn.rawTier) metaBits.push(`tier=\`${fn.rawTier}\``);
    if (fn.rawRung) metaBits.push(`rung=\`${fn.rawRung}\``);
    if (fn.rawSeverity) metaBits.push(`severity=\`${fn.rawSeverity}\``);
    if (fn.rawValueIfTrue) metaBits.push(`value_if_true=\`${fn.rawValueIfTrue}\``);
    if (fn.protocol) metaBits.push(`protocol=\`${escapeMdInline(fn.protocol)}\``);
    if (metaBits.length > 0) lines.push(`  - Machine Labels: ${metaBits.join(', ')}`);
    if (fn.whatWouldRefuteIt) {
      lines.push(`  - How we'd know this is wrong (\`what_would_refute_it\`): ${escapeMdInline(fn.whatWouldRefuteIt)}`);
    }
    if (fn.drafterFamily || fn.refuterFamily) {
      lines.push(
        `  - Seat Provenance: \`drafter_family=${escapeMdInline(fn.drafterFamily || 'n/a')}\` → \`refuter_family=${escapeMdInline(fn.refuterFamily || 'n/a')}\` (\`survived=${fn.survived}\`)`
      );
    }
    if (fn.resultDigest) {
      lines.push(`  - Result Digest (\`result_digest\`): \`${escapeMdInline(fn.resultDigest)}\``);
    }
    if (fn.commissionId) {
      lines.push(`  - Commission ID (\`refuter_commission_id\`): \`${escapeMdInline(fn.commissionId)}\``);
    }
    if (fn.refuterDefeater) {
      lines.push(`  - Adversarial Probe / Defeater: ${escapeMdInline(fn.refuterDefeater)}`);
    }
    if (fn.killReason) {
      lines.push(`  - Rejection Record: \`${escapeMdInline(fn.killReason)}\` (source index \`${fn.killIndex}\`)`);
    }
    if (fn.needsVerification) {
      lines.push(`  - Verification Handoff (\`needs_verification\`): \`${escapeMdInline(fn.needsVerification)}\``);
    }
  }
  lines.push('');
  lines.push('</details>');
  lines.push('');

  return lines.join('\n');
}

const EDITORIAL_CSS = `
  :root {
    --bg-canvas: #FAF8F4;
    --bg-surface: #FFFFFF;
    --bg-warm-well: #F4F1EA;
    --bg-subtle: #F8F6F1;
    --ink-primary: #1C232B;
    --ink-secondary: #434E5B;
    --ink-muted: #5C6877;
    --accent-navy: #1B365D;
    --border-warm: #E3DED3;
    --border-strong: #C9C1B2;
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    margin: 0;
    padding: 40px 24px 64px;
    background: var(--bg-canvas);
    color: var(--ink-primary);
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    font-size: 15.5px;
    line-height: 1.65;
    -webkit-font-smoothing: antialiased;
  }
  .report-shell {
    max-width: 940px;
    margin: 0 auto;
  }
  .masthead {
    border-bottom: 2px solid var(--ink-primary);
    padding-bottom: 22px;
    margin-bottom: 28px;
  }
  .eyebrow {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--accent-navy);
    margin: 0 0 8px;
  }
  .masthead h1 {
    font-family: 'Georgia', 'Iowan Old Style', 'Times New Roman', serif;
    font-size: 31px;
    line-height: 1.24;
    font-weight: 700;
    color: var(--ink-primary);
    margin: 0 0 12px;
  }
  .masthead-sub {
    font-size: 15px;
    color: var(--ink-secondary);
    margin: 0 0 14px;
  }
  .posture-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }
  .pill {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 600;
    line-height: 1.35;
    border: 1px solid transparent;
  }
  .pill-tier-grounded {
    background: #ECFDF3;
    color: #14532D;
    border-color: #A7F3D0;
  }
  .pill-tier-promising {
    background: #EFF6FF;
    color: #1E3A8A;
    border-color: #BFDBFE;
  }
  .pill-tier-speculative {
    background: #FFFBEB;
    color: #78350F;
    border-color: #FDE68A;
  }
  .pill-sev-critical {
    background: #FEF2F2;
    color: #991B1B;
    border-color: #FECACA;
  }
  .pill-sev-major {
    background: #FFF7ED;
    color: #9A3412;
    border-color: #FED7AA;
  }
  .pill-sev-minor {
    background: #F3F4F6;
    color: #374151;
    border-color: #D1D5DB;
  }
  .pill-rung-observed {
    background: #F0FDF4;
    color: #166534;
    border-color: #BBF7D0;
  }
  .pill-rung-corroborated {
    background: #EFF6FF;
    color: #1D4ED8;
    border-color: #BFDBFE;
  }
  .pill-rung-claimed {
    background: #FFFBEB;
    color: #92400E;
    border-color: #FDE68A;
  }
  .pill-rung-unverified {
    background: #F5F3FF;
    color: #5B21B6;
    border-color: #DDD6FE;
  }
  .pill-rung-refuted {
    background: #FEF2F2;
    color: #7F1D1D;
    border-color: #FECACA;
  }
  .pill-neutral {
    background: var(--bg-warm-well);
    color: var(--ink-secondary);
    border-color: var(--border-warm);
  }
  .qualification-callout {
    background: #FFFBEB;
    border: 1px solid #F59E0B;
    border-left: 5px solid #B45309;
    border-radius: 8px;
    padding: 18px 20px;
    margin-bottom: 28px;
  }
  .qualification-callout h2 {
    font-family: 'Georgia', 'Iowan Old Style', serif;
    font-size: 18px;
    color: #78350F;
    margin: 0 0 8px;
  }
  .qualification-callout ul {
    margin: 0;
    padding-left: 20px;
    color: #78350F;
    font-size: 14.5px;
  }
  .qualification-callout li + li {
    margin-top: 6px;
  }
  .section-block {
    margin-bottom: 36px;
  }
  .section-heading {
    font-family: 'Georgia', 'Iowan Old Style', 'Times New Roman', serif;
    font-size: 22px;
    line-height: 1.3;
    color: var(--ink-primary);
    border-bottom: 1px solid var(--border-strong);
    padding-bottom: 8px;
    margin: 0 0 16px;
  }
  .section-lead {
    font-size: 14.5px;
    color: var(--ink-secondary);
    margin: 0 0 16px;
  }
  .verdict-card {
    background: var(--bg-surface);
    border: 1px solid var(--border-warm);
    border-top: 4px solid var(--accent-navy);
    border-radius: 8px;
    padding: 24px 26px;
    box-shadow: 0 1px 3px rgba(28, 35, 43, 0.05);
    margin-bottom: 20px;
  }
  .verdict-label {
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--accent-navy);
    margin: 0 0 8px;
  }
  .verdict-statement {
    font-family: 'Georgia', 'Iowan Old Style', 'Times New Roman', serif;
    font-size: 19px;
    line-height: 1.48;
    color: var(--ink-primary);
    margin: 0 0 18px;
  }
  .dimension-strip {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 10px;
    padding: 14px 16px;
    background: var(--bg-warm-well);
    border-radius: 6px;
    margin-bottom: 18px;
  }
  .dimension-cell {
    font-size: 13.5px;
    color: var(--ink-secondary);
  }
  .dimension-cell strong {
    display: block;
    color: var(--ink-primary);
    margin-bottom: 3px;
  }
  .synthesis-prose p {
    margin: 0 0 12px;
    font-size: 15px;
    line-height: 1.66;
    color: var(--ink-primary);
  }
  .synthesis-prose p:last-child {
    margin-bottom: 0;
  }
  .card {
    background: var(--bg-surface);
    border: 1px solid var(--border-warm);
    border-radius: 8px;
    padding: 20px 22px;
    margin-bottom: 16px;
    box-shadow: 0 1px 2px rgba(28, 35, 43, 0.04);
  }
  .card-elevation {
    border-left: 4px solid var(--accent-navy);
  }
  .card-rejected {
    background: #FCFBFB;
    border-color: #E7D5D5;
    border-left: 4px solid #991B1B;
  }
  .card-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin-bottom: 10px;
  }
  .card-title {
    font-family: 'Georgia', 'Iowan Old Style', 'Times New Roman', serif;
    font-size: 17.5px;
    line-height: 1.38;
    color: var(--ink-primary);
    margin: 0 0 10px;
  }
  .card-body {
    font-size: 15px;
    line-height: 1.62;
    color: var(--ink-secondary);
    margin: 0;
  }
  .fn-badge {
    display: inline-block;
    margin-left: 5px;
    padding: 1px 6px;
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 13px;
    font-weight: 600;
    color: var(--accent-navy);
    background: var(--bg-warm-well);
    border: 1px solid var(--border-warm);
    border-radius: 4px;
    text-decoration: none;
    vertical-align: baseline;
  }
  .fn-badge:hover {
    background: #E8E3D8;
  }
  .sub-panel {
    margin-top: 14px;
    padding: 12px 15px;
    background: var(--bg-subtle);
    border: 1px solid var(--border-warm);
    border-radius: 6px;
    font-size: 14px;
    line-height: 1.56;
    color: var(--ink-primary);
  }
  .sub-panel + .sub-panel {
    margin-top: 10px;
  }
  .sub-panel-caveat {
    background: #FFFBEB;
    border-color: #FDE68A;
    color: #78350F;
  }
  .two-col-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 12px;
    margin: 12px 0;
  }
  .correspondence-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 14px;
    font-size: 14px;
  }
  .correspondence-table th,
  .correspondence-table td {
    text-align: left;
    vertical-align: top;
    padding: 10px 12px;
    border: 1px solid var(--border-warm);
  }
  .correspondence-table th {
    background: var(--bg-warm-well);
    color: var(--ink-primary);
    font-weight: 600;
  }
  .minor-list {
    list-style: none;
    padding: 0;
    margin: 12px 0 0;
  }
  .minor-list li {
    background: var(--bg-surface);
    border: 1px solid var(--border-warm);
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 10px;
    font-size: 14.5px;
  }
  .subsection-heading {
    font-family: 'Georgia', 'Iowan Old Style', serif;
    font-size: 17px;
    color: var(--ink-primary);
    margin: 20px 0 10px;
  }
  details.provenance-appendix {
    margin-top: 40px;
    background: var(--bg-warm-well);
    border: 1px solid var(--border-strong);
    border-radius: 8px;
    padding: 14px 20px;
  }
  details.provenance-appendix > summary {
    cursor: pointer;
    font-weight: 700;
    font-size: 14.5px;
    color: var(--ink-primary);
    list-style-position: inside;
  }
  .appendix-body {
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid var(--border-warm);
    font-size: 13.5px;
    color: var(--ink-secondary);
  }
  .appendix-run-meta {
    padding: 10px 12px;
    background: var(--bg-surface);
    border: 1px solid var(--border-warm);
    border-radius: 6px;
    margin-bottom: 14px;
    font-size: 13px;
  }
  .appendix-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .appendix-item {
    background: var(--bg-surface);
    border: 1px solid var(--border-warm);
    border-radius: 6px;
    padding: 12px 14px;
    margin-bottom: 10px;
    font-size: 13px;
    line-height: 1.55;
  }
  .appendix-item code {
    font-family: 'JetBrains Mono', 'Cascadia Code', Consolas, monospace;
    font-size: 13px;
    background: var(--bg-subtle);
    padding: 1px 5px;
    border-radius: 3px;
    word-break: break-all;
  }
  .appendix-item dl {
    margin: 8px 0 0;
    display: grid;
    grid-template-columns: minmax(170px, 230px) 1fr;
    gap: 4px 12px;
  }
  .appendix-item dt {
    font-weight: 600;
    color: var(--ink-primary);
  }
  .appendix-item dd {
    margin: 0;
    word-break: break-word;
  }
  .gpm-card {
    background: var(--bg-surface);
    border: 1px solid var(--border-warm);
    border-radius: 10px;
    padding: 18px 20px;
    box-shadow: 0 1px 3px rgba(28, 35, 43, 0.04);
  }
  .gpm-radio {
    position: absolute;
    opacity: 0;
    pointer-events: none;
  }
  .gpm-lens-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
    margin: 10px 0 14px;
  }
  .gpm-lens-pill {
    display: inline-flex;
    align-items: center;
    padding: 5px 11px;
    border-radius: 999px;
    font-size: 12.5px;
    font-weight: 600;
    background: var(--bg-warm-well);
    color: var(--ink-secondary);
    border: 1px solid var(--border-strong);
    cursor: pointer;
    user-select: none;
  }
  .gpm-lens-pill:hover {
    border-color: var(--accent-navy);
    color: var(--accent-navy);
  }
  #gpm-tab-0:checked ~ .gpm-lens-bar label[for="gpm-tab-0"],
  #gpm-tab-1:checked ~ .gpm-lens-bar label[for="gpm-tab-1"],
  #gpm-tab-2:checked ~ .gpm-lens-bar label[for="gpm-tab-2"],
  #gpm-tab-3:checked ~ .gpm-lens-bar label[for="gpm-tab-3"],
  #gpm-tab-4:checked ~ .gpm-lens-bar label[for="gpm-tab-4"],
  #gpm-tab-5:checked ~ .gpm-lens-bar label[for="gpm-tab-5"] {
    background: var(--accent-navy);
    color: #FFFFFF;
    border-color: var(--accent-navy);
  }
  .gpm-grid {
    display: grid;
    grid-template-columns: minmax(290px, 410px) 1fr;
    gap: 18px;
    align-items: start;
  }
  @media (max-width: 780px) {
    .gpm-grid { grid-template-columns: 1fr; }
  }
  .gpm-svg-layer { display: none; }
  #gpm-tab-0:checked ~ .gpm-grid .gpm-layer-0,
  #gpm-tab-1:checked ~ .gpm-grid .gpm-layer-1,
  #gpm-tab-2:checked ~ .gpm-grid .gpm-layer-2,
  #gpm-tab-3:checked ~ .gpm-grid .gpm-layer-3,
  #gpm-tab-4:checked ~ .gpm-grid .gpm-layer-4,
  #gpm-tab-5:checked ~ .gpm-grid .gpm-layer-5 {
    display: block;
  }
  .gpm-disk-svg {
    width: 100%;
    max-width: 400px;
    height: auto;
    display: block;
    margin: 0 auto;
    border-radius: 50%;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.18);
  }
  .gpm-shell-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .gpm-shell-table th,
  .gpm-shell-table td {
    padding: 7px 9px;
    border: 1px solid var(--border-warm);
    text-align: left;
    vertical-align: top;
  }
  .gpm-shell-table th {
    background: var(--bg-warm-well);
    font-weight: 600;
    color: var(--ink-primary);
  }
  @media print {
    @page { margin: 0.6in; }
    body {
      background: #FFFFFF;
      padding: 0;
      font-size: 13.5px;
    }
    .report-shell { max-width: 100%; }
    .card, .verdict-card, .qualification-callout, .appendix-item {
      break-inside: avoid;
      page-break-inside: avoid;
      box-shadow: none;
    }
  }
`;

/**
 * Deterministically render a graded Gandalf JSON object into a self-contained executive HTML report.
 * Zero post-grade LLM calls; XSS-safe; preserves earned uncertainty stamps and kill_log entries.
 */
export function renderExecutiveHtml(gradedOutput, meta = {}) {
  const m = buildReportModel(gradedOutput, meta);
  const out = [];

  out.push('<!DOCTYPE html>');
  out.push('<html lang="en">');
  out.push('<head>');
  out.push('  <meta charset="utf-8">');
  out.push('  <meta name="viewport" content="width=device-width, initial-scale=1">');
  out.push(`  <title>${escapeHtml(m.title)}</title>`);
  out.push(`  <style>${EDITORIAL_CSS}</style>`);
  out.push('</head>');
  out.push('<body>');
  out.push('  <main class="report-shell">');

  // Masthead
  out.push('    <header class="masthead">');
  out.push('      <p class="eyebrow">Gandalf Deep-Think Advisory Report</p>');
  out.push(`      <h1>${escapeHtml(m.title)}</h1>`);
  if (m.subject || m.date) {
    const subBits = [m.subject, m.date].filter(Boolean).map(escapeHtml);
    out.push(`      <p class="masthead-sub">${subBits.join(' &middot; ')}</p>`);
  }
  out.push('      <div class="posture-row">');
  if (m.crossModel) {
    out.push(
      '        <span class="pill pill-tier-grounded">Cross-Family Adversarial Review Completed</span>'
    );
  } else {
    out.push(
      '        <span class="pill pill-tier-speculative">Single-Family Pass (Unverified Across Model Families)</span>'
    );
  }
  if (m.degraded) {
    out.push('        <span class="pill pill-sev-major">Degraded Scope — See Qualification</span>');
  }
  out.push(
    `        <span class="pill pill-neutral">${m.diagnoseItems.length} Diagnosis Item${m.diagnoseItems.length === 1 ? '' : 's'} &middot; ${m.elevationItems.length} Recommended Elevation${m.elevationItems.length === 1 ? '' : 's'} &middot; ${m.rejectedItems.length} Rejected in Review</span>`
  );
  if (m.supplementHref) {
    out.push(
      `        <a class="pill pill-tier-promising" href="${escapeHtml(m.supplementHref)}" style="text-decoration:none">&#129517; Open Interactive Gandalf Poincar&eacute; Map Supplement &rarr;</a>`
    );
  }
  out.push('      </div>');
  out.push('    </header>');

  // Prominent Scope & Verification Qualification callout when degraded or cross_model:false
  if (m.qualificationNeeded) {
    out.push('    <section class="qualification-callout" role="note" aria-label="Scope and Verification Qualification">');
    out.push('      <h2>Scope &amp; Verification Qualification</h2>');
    out.push('      <ul>');
    for (const reason of m.qualificationReasons) {
      out.push(`        <li>${escapeHtml(reason)}</li>`);
    }
    out.push('      </ul>');
    out.push('    </section>');
  }

  // 1. Executive Summary & Verdict Card
  out.push('    <section class="section-block" id="executive-summary">');
  out.push('      <h2 class="section-heading">Executive Summary &amp; Verdict</h2>');
  out.push('      <div class="verdict-card">');
  out.push('        <p class="verdict-label">Bottom-Line Verdict</p>');
  out.push(`        <p class="verdict-statement">${escapeHtml(m.verdict)}</p>`);
  if (m.dimensionSummaries.length > 0) {
    out.push('        <div class="dimension-strip">');
    for (const d of m.dimensionSummaries) {
      out.push('          <div class="dimension-cell">');
      out.push(`            <strong>${escapeHtml(d.dimension)}</strong>`);
      out.push(`            <span>${escapeHtml(d.rungLabel || d.tierLabel)}</span>`);
      out.push('          </div>');
    }
    out.push('        </div>');
  }
  out.push('        <div class="synthesis-prose">');
  for (const p of m.narrativeParagraphs) {
    out.push(`          ${renderParagraphHtml(p)}`);
  }
  out.push('        </div>');
  out.push('      </div>');
  out.push('    </section>');

  // 1b. Interactive Poincaré Knowledge & Risk State Map (Pure-CSS Möbius Gyrovector Lenses + SVG Geodesics)
  const pmap = buildPoincareKnowledgeMap(m);
  if (pmap.nodes.length > 1) {
    const lensTargets = [
      { id: 0, title: 'Origin: Central Verdict', node: pmap.nodes[0] },
      ...pmap.activeSectors.slice(0, 5).map((sec, idx) => ({
        id: idx + 1,
        title: `Möbius Focus: ${sec.label}`,
        node: pmap.nodes.find((nd) => nd.key === sec.key) || pmap.nodes[0],
      })),
    ];
    out.push('    <section class="section-block" id="poincare-knowledge-map">');
    out.push('      <h2 class="section-heading">Poincar&eacute; Knowledge &amp; Risk State Map</h2>');
    out.push('      <div class="gpm-card">');
    if (m.supplementHref) {
      out.push(
        `        <div style="margin-bottom:10px"><a class="pill pill-tier-promising" href="${escapeHtml(m.supplementHref)}" style="text-decoration:none">&#129517; Launch Full Interactive Click-to-Zoom Gandalf Poincar&eacute; Map Supplement &rarr;</a></div>`
      );
    }
    out.push(
      '        <p class="card-body" style="margin-bottom:8px">Sarkar hyperbolic layout with Radial Importance Promotion: high-importance verified claims sit near the origin <code>(0, 0)</code>, exploratory and premortem items occupy mid shells, and refuted proposals recede to the outer Boneyard horocycle. Select any M&ouml;bius focus lens below to translate that sector isometrically to the origin, or click any numbered node <code>[n]</code> to jump to its evidence card.</p>'
    );
    for (const lt of lensTargets) {
      const checkedAttr = lt.id === 0 ? ' checked' : '';
      out.push(
        `        <input class="gpm-radio" type="radio" name="gpm-tab" id="gpm-tab-${lt.id}"${checkedAttr}>`
      );
    }
    out.push('        <div class="gpm-lens-bar">');
    for (const lt of lensTargets) {
      out.push(`          <label class="gpm-lens-pill" for="gpm-tab-${lt.id}">${escapeHtml(lt.title)}</label>`);
    }
    out.push('        </div>');
    out.push('        <div class="gpm-grid">');
    out.push('          <div>');
    for (const lt of lensTargets) {
      out.push(`            <div class="gpm-svg-layer gpm-layer-${lt.id}">`);
      out.push(renderPoincareSvgLayer(pmap.nodes, lt.node));
      out.push('            </div>');
    }
    out.push('          </div>');
    out.push('          <div>');
    out.push('            <table class="gpm-shell-table">');
    out.push('              <thead><tr><th>Shell</th><th>Node</th><th>r_eff</th><th>Posture</th></tr></thead>');
    out.push('              <tbody>');
    for (const nd of pmap.nodes) {
      if (nd.shell === 'Sector Hub') continue;
      const fnLink = nd.fn ? ` <a class="fn-badge" href="#provref-${nd.fn}">[${nd.fn}]</a>` : '';
      out.push(
        `                <tr><td>${escapeHtml(nd.shell)}</td><td>${escapeHtml(nd.label)}${fnLink}</td><td><code>${nd.rEff.toFixed(2)}</code></td><td>${escapeHtml(nd.posture)}</td></tr>`
      );
    }
    out.push('              </tbody>');
    out.push('            </table>');
    out.push('          </div>');
    out.push('        </div>');
    out.push('      </div>');
    out.push('    </section>');
  }

  // 2. What Is Really Going On (Ranked Diagnosis)
  out.push('    <section class="section-block" id="ranked-diagnosis">');
  out.push('      <h2 class="section-heading">What Is Really Going On (Ranked Diagnosis)</h2>');
  if (m.diagnoseItems.length === 0) {
    out.push(
      `      <div class="card"><p class="card-body">${escapeHtml(
        m.isSoundVerdict
          ? 'No structural defects were identified; the assessed artifact is sound.'
          : 'No separate structural diagnosis items were recorded beyond the executive synthesis above.'
      )}</p></div>`
    );
  } else {
    m.diagnoseItems.forEach((d, idx) => {
      out.push('      <article class="card">');
      out.push('        <div class="card-meta">');
      if (d.severityLabel) {
        out.push(`          <span class="pill ${d.severityCss}">${escapeHtml(d.severityLabel)}</span>`);
      }
      out.push(`          <span class="pill ${d.rungCss}">${escapeHtml(d.rungLabel)}</span>`);
      out.push('        </div>');
      out.push(
        `        <h3 class="card-title">${idx + 1}. ${escapeHtml(d.verdict)} <a class="fn-badge" id="provref-${d.fn}" href="#prov-${d.fn}" title="See provenance footnote ${d.fn}">[${d.fn}]</a></h3>`
      );
      out.push(`        <p class="card-body">${escapeHtml(d.reasoning)}</p>`);
      out.push('      </article>');
    });
  }
  if (m.nitpickItems.length > 0) {
    out.push('      <h3 class="subsection-heading">Additional Polish &amp; Minor Observations</h3>');
    out.push('      <ul class="minor-list">');
    for (const n of m.nitpickItems) {
      out.push('        <li>');
      out.push(
        `          <strong>${escapeHtml(n.verdict)}</strong> <span class="pill ${n.rungCss}">${escapeHtml(n.rungLabel)}</span> <a class="fn-badge" id="provref-${n.fn}" href="#prov-${n.fn}">[${n.fn}]</a> &mdash; ${escapeHtml(n.reasoning)}`
      );
      out.push('        </li>');
    }
    out.push('      </ul>');
  }
  out.push('    </section>');

  // 3. Best-in-Class Landscape Framing
  if (m.situateItems.length > 0) {
    out.push('    <section class="section-block" id="landscape-framing">');
    out.push('      <h2 class="section-heading">Best-in-Class Landscape Framing</h2>');
    for (const s of m.situateItems) {
      out.push('      <article class="card">');
      out.push('        <div class="card-meta">');
      out.push(`          <span class="pill ${s.rungCss}">${escapeHtml(s.rungLabel)}</span>`);
      out.push('        </div>');
      out.push(
        `        <h3 class="card-title">${escapeHtml(s.verdict)} <a class="fn-badge" id="provref-${s.fn}" href="#prov-${s.fn}">[${s.fn}]</a></h3>`
      );
      out.push(`        <p class="card-body">${escapeHtml(s.reasoning)}</p>`);
      if (s.skeleton) {
        out.push(
          `        <div class="sub-panel"><strong>Underlying Structural Challenge:</strong> ${escapeHtml(s.skeleton)}</div>`
        );
      }
      if (s.structureAnswer) {
        out.push(
          `        <div class="sub-panel"><strong>Reference Architecture Pattern:</strong> ${escapeHtml(s.structureAnswer)}</div>`
        );
      }
      if (s.correspondences.length > 0) {
        out.push('        <table class="correspondence-table">');
        out.push('          <thead><tr><th>Proven Pattern in Reference Field</th><th>Application to This Effort</th></tr></thead>');
        out.push('          <tbody>');
        for (const c of s.correspondences) {
          out.push(
            `            <tr><td>${escapeHtml(c.source)}</td><td>${escapeHtml(c.target)}</td></tr>`
          );
        }
        out.push('          </tbody>');
        out.push('        </table>');
      }
      if (s.outsideViewBaseRate) {
        out.push(
          `        <div class="sub-panel"><strong>Outside-View Base Rate:</strong> ${escapeHtml(s.outsideViewBaseRate)}</div>`
        );
      }
      if (s.unverifiedExternalComparison) {
        out.push(
          '        <div class="sub-panel sub-panel-caveat"><strong>Verification Caveat:</strong> External reference patterns and base-rate comparisons above have not yet been independently verified by a dedicated research pass and remain Claimed (Needs Verification).</div>'
        );
      }
      out.push('      </article>');
    }
    out.push('    </section>');
  }

  // 4. Coming Problems (Premortem)
  if (m.anticipateItems.length > 0) {
    out.push('    <section class="section-block" id="coming-problems">');
    out.push('      <h2 class="section-heading">Coming Problems (Premortem)</h2>');
    m.anticipateItems.forEach((a, idx) => {
      out.push('      <article class="card">');
      out.push('        <div class="card-meta">');
      if (a.severityLabel) {
        out.push(`          <span class="pill ${a.severityCss}">${escapeHtml(a.severityLabel)}</span>`);
      }
      out.push(`          <span class="pill ${a.rungCss}">${escapeHtml(a.rungLabel)}</span>`);
      out.push('        </div>');
      out.push(
        `        <h3 class="card-title">${idx + 1}. ${escapeHtml(a.verdict)} <a class="fn-badge" id="provref-${a.fn}" href="#prov-${a.fn}">[${a.fn}]</a></h3>`
      );
      if (a.futureCondition || a.enablingAssumption) {
        out.push('        <div class="two-col-grid">');
        if (a.futureCondition) {
          out.push(
            `          <div class="sub-panel"><strong>Coming Failure Mode:</strong> ${escapeHtml(a.futureCondition)}</div>`
          );
        }
        if (a.enablingAssumption) {
          out.push(
            `          <div class="sub-panel"><strong>Enabling Assumption:</strong> ${escapeHtml(a.enablingAssumption)}</div>`
          );
        }
        out.push('        </div>');
      }
      out.push(`        <p class="card-body">${escapeHtml(a.reasoning)}</p>`);
      out.push('      </article>');
    });
    out.push('    </section>');
  }

  // 5. Recommended Elevations
  out.push('    <section class="section-block" id="recommended-elevations">');
  out.push('      <h2 class="section-heading">Recommended Elevations</h2>');
  if (m.elevationItems.length === 0) {
    out.push(
      '      <div class="card"><p class="card-body">No forward elevations survived or were proposed on this pass.</p></div>'
    );
  } else {
    m.elevationItems.forEach((e, idx) => {
      out.push('      <article class="card card-elevation">');
      out.push('        <div class="card-meta">');
      out.push(`          <span class="pill ${e.tierCss}">${escapeHtml(e.tierLabel)}</span>`);
      out.push(`          <span class="pill pill-neutral">${escapeHtml(e.valueLabel)}</span>`);
      if (e.rungLabel) {
        out.push(`          <span class="pill ${e.rungCss}">${escapeHtml(e.rungLabel)}</span>`);
      }
      out.push('        </div>');
      out.push(
        `        <h3 class="card-title">${idx + 1}. ${escapeHtml(e.verdict)} <a class="fn-badge" id="provref-${e.fn}" href="#prov-${e.fn}">[${e.fn}]</a></h3>`
      );
      out.push(`        <p class="card-body">${escapeHtml(e.reasoning)}</p>`);
      if (e.falsificationTest) {
        out.push(
          `        <div class="sub-panel"><strong>Falsification Test (How we&#39;d know this is wrong):</strong> ${escapeHtml(e.falsificationTest)}</div>`
        );
      }
      if (e.reviewerVerdictNote) {
        out.push(
          `        <div class="sub-panel"><strong>Independent Reviewer Assessment &amp; Boundary Conditions:</strong> ${escapeHtml(e.reviewerVerdictNote)}</div>`
        );
      }
      out.push('      </article>');
    });
  }
  out.push('    </section>');

  // 6. Ideas Tested & Rejected by Adversarial Review
  if (m.rejectedItems.length > 0) {
    out.push('    <section class="section-block" id="ideas-tested-and-rejected">');
    out.push('      <h2 class="section-heading">Ideas Tested &amp; Rejected by Adversarial Review</h2>');
    out.push(
      '      <p class="section-lead">The following candidate proposals or claims were stress-tested against concrete falsification checks and rejected when the named defeater held up.</p>'
    );
    for (const r of m.rejectedItems) {
      out.push('      <article class="card card-rejected">');
      out.push('        <div class="card-meta">');
      out.push(`          <span class="pill pill-rung-refuted">${escapeHtml(r.statusLabel)}</span>`);
      out.push('        </div>');
      out.push(
        `        <h3 class="card-title">${escapeHtml(r.humanTitle)} <a class="fn-badge" id="provref-${r.fn}" href="#prov-${r.fn}">[${r.fn}]</a></h3>`
      );
      out.push(
        `        <div class="sub-panel"><strong>Concrete Defeater That Falsified It:</strong> ${escapeHtml(r.defeaterText)}</div>`
      );
      out.push('      </article>');
    }
    out.push('    </section>');
  }

  // 7. Collapsed Verification & Machine Provenance Appendix
  out.push('    <details class="provenance-appendix" id="provenance-appendix">');
  out.push(
    `      <summary>Verification &amp; Machine Provenance Appendix (${m.footnotes.length} Footnote${m.footnotes.length === 1 ? '' : 's'} &middot; Audit Trail)</summary>`
  );
  out.push('      <div class="appendix-body">');
  out.push('        <div class="appendix-run-meta">');
  out.push(
    `          <strong>Machine Envelope:</strong> <code>schema_version=${escapeHtml(m.schemaVersion)}</code> &middot; <code>cross_model=${m.crossModel}</code> &middot; <code>cross_model_requested=${m.crossModelRequested}</code> &middot; <code>degraded=${m.degraded}</code>`
  );
  if (m.hostNote) {
    out.push(`<br><strong>Host Conformance Note:</strong> <code>${escapeHtml(m.hostNote)}</code>`);
  }
  out.push('        </div>');
  out.push('        <ol class="appendix-list">');
  for (const fn of m.footnotes) {
    out.push(`          <li class="appendix-item" id="prov-${fn.num}">`);
    out.push(
      `            <strong>[${fn.num}] &rarr; <code>${escapeHtml(fn.rawId)}</code></strong> <span>(${escapeHtml(fn.category)})</span> <a href="#provref-${fn.num}" title="Jump back to report card">&uarr;</a>`
    );
    out.push('            <dl>');
    if (fn.rawTier) {
      out.push(`              <dt>Earned Tier</dt><dd><code>${escapeHtml(fn.rawTier)}</code> &mdash; ${escapeHtml(fn.earnedLabel)}</dd>`);
    }
    if (fn.rawRung) {
      out.push(`              <dt>Evidence Rung</dt><dd><code>${escapeHtml(fn.rawRung)}</code></dd>`);
    }
    if (fn.rawSeverity) {
      out.push(`              <dt>Severity</dt><dd><code>${escapeHtml(fn.rawSeverity)}</code></dd>`);
    }
    if (fn.rawValueIfTrue) {
      out.push(`              <dt>Value If True</dt><dd><code>${escapeHtml(fn.rawValueIfTrue)}</code></dd>`);
    }
    if (fn.protocol) {
      out.push(`              <dt>Diagnose Protocol</dt><dd><code>${escapeHtml(fn.protocol)}</code></dd>`);
    }
    if (fn.whatWouldRefuteIt) {
      out.push(
        `              <dt>How we&#39;d know this is wrong (<code>what_would_refute_it</code>)</dt><dd>${escapeHtml(fn.whatWouldRefuteIt)}</dd>`
      );
    }
    if (fn.drafterFamily || fn.refuterFamily) {
      out.push(
        `              <dt>Drafter / Refuter Seats</dt><dd><code>drafter_family=${escapeHtml(fn.drafterFamily || 'n/a')}</code> &rarr; <code>refuter_family=${escapeHtml(fn.refuterFamily || 'n/a')}</code> (<code>survived=${fn.survived}</code>)</dd>`
      );
    }
    if (fn.resultDigest) {
      out.push(`              <dt>Result Digest (<code>result_digest</code>)</dt><dd><code>${escapeHtml(fn.resultDigest)}</code></dd>`);
    }
    if (fn.commissionId) {
      out.push(
        `              <dt>Commission ID (<code>refuter_commission_id</code>)</dt><dd><code>${escapeHtml(fn.commissionId)}</code></dd>`
      );
    }
    if (fn.refuterDefeater) {
      out.push(`              <dt>Adversarial Defeater Probe</dt><dd>${escapeHtml(fn.refuterDefeater)}</dd>`);
    }
    if (fn.killReason) {
      out.push(
        `              <dt>Rejection Record</dt><dd><code>${escapeHtml(fn.killReason)}</code> (index <code>${fn.killIndex}</code>)</dd>`
      );
    }
    if (fn.needsVerification) {
      out.push(
        `              <dt>Verification Handoff (<code>needs_verification</code>)</dt><dd><code>${escapeHtml(fn.needsVerification)}</code></dd>`
      );
    }
    out.push('            </dl>');
    out.push('          </li>');
  }
  out.push('        </ol>');
  out.push('      </div>');
  out.push('    </details>');

  out.push('  </main>');
  out.push('</body>');
  out.push('</html>\n');

  return out.join('\n');
}

/** Derive the companion interactive Poincaré Map supplement path (`<stem>-poincare-map.html`). */
export function derivePoincareSupplementPath(reportPath) {
  const abs = resolve(reportPath);
  const dir = dirname(abs);
  const ext = extname(abs);
  const stem = ext ? basename(abs, ext) : basename(abs);
  return join(dir, `${stem}-poincare-map.html`);
}

/**
 * Render the standalone Interactive 2D Möbius-Zoomable Gandalf Poincaré Knowledge & Risk Map
 * supplement HTML file that accompanies every Gandalf report.
 */
export function renderGandalfPoincareSupplementHtml(gradedOutput, meta = {}) {
  const m = buildReportModel(gradedOutput, meta);
  const pmap = buildPoincareKnowledgeMap(m);
  const detailByFn = {};
  for (const d of m.diagnoseItems) detailByFn[d.fn] = { kind: 'Diagnosis', body: d.reasoning, extra: '' };
  for (const n of m.nitpickItems) detailByFn[n.fn] = { kind: 'Observation', body: n.reasoning, extra: '' };
  for (const s of m.situateItems) {
    detailByFn[s.fn] = {
      kind: 'Landscape Situate',
      body: s.reasoning,
      extra: [s.skeleton && `Skeleton: ${s.skeleton}`, s.structureAnswer && `Pattern: ${s.structureAnswer}`].filter(Boolean).join('\n'),
    };
  }
  for (const a of m.anticipateItems) {
    detailByFn[a.fn] = {
      kind: 'Premortem',
      body: a.reasoning,
      extra: [a.futureCondition && `Failure Mode: ${a.futureCondition}`, a.enablingAssumption && `Assumption: ${a.enablingAssumption}`].filter(Boolean).join('\n'),
    };
  }
  for (const e of m.elevationItems) {
    detailByFn[e.fn] = {
      kind: 'Recommended Elevation',
      body: e.reasoning,
      extra: e.falsificationTest ? `Falsification Test: ${e.falsificationTest}` : '',
    };
  }
  for (const r of m.rejectedItems) {
    detailByFn[r.fn] = {
      kind: 'Refuted / Rejected Hypothesis',
      body: `Concrete Defeater: ${r.defeaterText}`,
      extra: '',
    };
  }

  const enrichedNodes = pmap.nodes.map((nd) => {
    const det = nd.fn ? detailByFn[nd.fn] : null;
    return {
      key: nd.key,
      parentKey: nd.parentKey,
      fn: nd.fn,
      shell: nd.shell,
      color: nd.color,
      importance: nd.importance,
      boneyard: nd.boneyard,
      rEff: Number(nd.rEff.toFixed(3)),
      zx: Number(nd.zx.toFixed(6)),
      zy: Number(nd.zy.toFixed(6)),
      label: nd.label,
      posture: nd.posture,
      kindLabel: det ? det.kind : nd.key === 'origin' ? 'Central Verdict' : 'Sector Hub',
      body: det ? det.body : nd.key === 'origin' ? m.narrativeParagraphs.join('\n\n') : `${nd.label} (${nd.posture})`,
      extra: det ? det.extra : '',
    };
  });

  const payloadJson = JSON.stringify({
    title: m.title,
    verdict: m.verdict,
    reportBackHref: m.reportBackHref || '',
    nodes: enrichedNodes,
  }).replace(/<\//g, '<\\/');

  const backBtnHtml = m.reportBackHref
    ? `<a class="nav-btn" href="${escapeHtml(m.reportBackHref)}">&larr; Back to Gandalf Executive Report</a>`
    : '';

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(m.title)} — Interactive Gandalf Poincaré Map Supplement</title>
<style>
  :root { --bg:#070b14; --panel:#0f172a; --border:#1e293b; --ink:#f1f5f9; --muted:#94a3b8; --sky:#38bdf8; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font-family:Inter,system-ui,sans-serif; font-size:14px; line-height:1.55; }
  .top { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; padding:14px 22px; background:#0b1120; border-bottom:1px solid var(--border); }
  .top h1 { margin:0; font-size:17px; font-weight:800; color:#f8fafc; }
  .controls { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  button, a.nav-btn { padding:6px 12px; border-radius:7px; border:1px solid #334155; background:#0f172a; color:#f1f5f9; font-size:12.5px; font-weight:600; text-decoration:none; cursor:pointer; }
  button:hover, a.nav-btn:hover { border-color:var(--sky); color:#7dd3fc; }
  button.primary { background:rgba(16,185,129,0.16); border-color:rgba(16,185,129,0.5); color:#6ee7b7; }
  .grid { display:grid; grid-template-columns:minmax(420px,620px) 1fr; gap:18px; padding:20px 22px; max-width:1560px; margin:0 auto; align-items:start; }
  @media (max-width:1040px) { .grid { grid-template-columns:1fr; } }
  .card { background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:16px 18px; }
  svg#gpmSvg { width:100%; max-width:580px; height:auto; aspect-ratio:1/1; display:block; margin:10px auto; border-radius:50%; background:radial-gradient(circle at 50% 50%, #111c33 0%, #09101f 68%, #050811 100%); box-shadow:0 0 0 1px rgba(56,189,248,0.3), 0 18px 42px rgba(0,0,0,0.55); user-select:none; }
  .pill { display:inline-flex; padding:3px 9px; border-radius:999px; font-size:11.5px; font-weight:700; background:rgba(56,189,248,0.14); color:#7dd3fc; border:1px solid rgba(56,189,248,0.35); }
  .body-box { margin-top:12px; padding:12px 14px; border-radius:8px; background:#070c16; border:1px solid #1e293b; white-space:pre-wrap; color:#cbd5e1; font-size:13.5px; }
  .node-list { display:flex; flex-direction:column; gap:6px; max-height:360px; overflow-y:auto; margin-top:10px; }
  .node-row { padding:8px 10px; border-radius:8px; background:#080e1a; border:1px solid #1e293b; cursor:pointer; display:flex; justify-content:space-between; gap:10px; align-items:center; }
  .node-row:hover { border-color:var(--sky); }
</style>
</head>
<body>
<header class="top">
  <div>
    <div style="font-size:11px;font-weight:700;color:#7dd3fc;text-transform:uppercase;letter-spacing:.06em">Gandalf Poincaré Map Supplement</div>
    <h1>&#129517; ${escapeHtml(m.title)}</h1>
  </div>
  <div class="controls">
    <button type="button" class="primary" id="resetBtn">&#8634; Reset Origin (0, 0)</button>
    ${backBtnHtml}
  </div>
</header>
<main class="grid">
  <section class="card">
    <div style="font-size:12.5px;color:#94a3b8;text-align:center">
      <b>Click any node</b> on the Poincaré Disk (or in the list on the right) to execute an isometric <b>M&ouml;bius gyrovector translation</b> bringing that claim or risk sector to center focus <code>(0, 0)</code>.
    </div>
    <svg id="gpmSvg" viewBox="-1.08 -1.08 2.16 2.16" aria-label="Interactive Gandalf Poincaré Disk"></svg>
  </section>
  <section style="display:flex;flex-direction:column;gap:14px">
    <div class="card">
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <span class="pill" id="selShell">Core Origin</span>
        <span class="pill" id="selPosture">Executive Verdict</span>
        <span class="pill" id="selReff">r_eff = 0.00</span>
      </div>
      <h2 id="selTitle" style="margin:10px 0 4px;font-size:17px;color:#f8fafc"></h2>
      <div class="body-box" id="selBody"></div>
    </div>
    <div class="card">
      <h3 style="margin:0;font-size:14.5px;color:#f8fafc">All Knowledge, Elevation &amp; Risk Nodes (Click to M&ouml;bius-Zoom)</h3>
      <div class="node-list" id="nodeList"></div>
    </div>
  </section>
</main>
<script>
(function() {
  const DATA = ${payloadJson};
  const nodes = DATA.nodes || [];
  const byKey = {};
  const disp = {};
  nodes.forEach(n => { byKey[n.key] = n; disp[n.key] = [n.zx, n.zy]; });
  let selKey = (nodes[0] && nodes[0].key) || 'origin';

  function mobius(zx, zy, fx, fy) {
    const nr = zx - fx, ni = zy - fy;
    const dr = 1 - (fx * zx + fy * zy), di = -(fx * zy - fy * zx);
    const den = dr * dr + di * di;
    if (den < 1e-12) return [0, 0];
    let ox = (nr * dr + ni * di) / den, oy = (ni * dr - nr * di) / den;
    const m = Math.hypot(ox, oy);
    if (m > 0.96) { ox *= 0.96 / m; oy *= 0.96 / m; }
    return [ox, oy];
  }

  function geoD(x1, y1, x2, y2) {
    const cr = x1 * y2 - y1 * x2, seg = Math.hypot(x2 - x1, y2 - y1);
    if (Math.abs(cr) < 1e-3 || seg < 0.03) return 'M ' + x1.toFixed(4) + ' ' + y1.toFixed(4) + ' L ' + x2.toFixed(4) + ' ' + y2.toFixed(4);
    const r1 = 0.5 * (x1 * x1 + y1 * y1 + 1), r2 = 0.5 * (x2 * x2 + y2 * y2 + 1);
    const cx = (r1 * y2 - r2 * y1) / cr, cy = (x1 * r2 - x2 * r1) / cr;
    const R = Math.sqrt(Math.max(0.0001, cx * cx + cy * cy - 1));
    if (!isFinite(R) || R > 25) return 'M ' + x1.toFixed(4) + ' ' + y1.toFixed(4) + ' L ' + x2.toFixed(4) + ' ' + y2.toFixed(4);
    return 'M ' + x1.toFixed(4) + ' ' + y1.toFixed(4) + ' A ' + R.toFixed(4) + ' ' + R.toFixed(4) + ' 0 0 ' + (cr > 0 ? 0 : 1) + ' ' + x2.toFixed(4) + ' ' + y2.toFixed(4);
  }

  function draw() {
    const svg = document.getElementById('gpmSvg');
    const out = [
      '<circle cx="0" cy="0" r="1.0" fill="none" stroke="#334155" stroke-width="0.01"/>',
      '<circle cx="0" cy="0" r="0.38" fill="none" stroke="rgba(56,189,248,0.18)" stroke-width="0.004" stroke-dasharray="0.015,0.015"/>',
      '<circle cx="0" cy="0" r="0.72" fill="none" stroke="rgba(56,189,248,0.18)" stroke-width="0.004" stroke-dasharray="0.015,0.015"/>',
      '<circle cx="0" cy="0" r="0.90" fill="none" stroke="rgba(248,113,113,0.28)" stroke-width="0.004" stroke-dasharray="0.02,0.02"/>'
    ];
    nodes.forEach(n => {
      if (!n.parentKey || !disp[n.parentKey]) return;
      const [x1, y1] = disp[n.parentKey], [x2, y2] = disp[n.key];
      out.push('<path d="' + geoD(x1, y1, x2, y2) + '" fill="none" stroke="' + (n.boneyard ? 'rgba(248,113,113,0.34)' : 'rgba(125,211,252,0.45)') + '" stroke-width="0.0055"/>');
    });
    const ord = nodes.slice().sort((a, b) => Math.hypot(...disp[b.key]) - Math.hypot(...disp[a.key]));
    ord.forEach(n => {
      const [x, y] = disp[n.key];
      const r2 = Math.min(0.95, x * x + y * y);
      const rad = Math.max(0.018, (n.key === 'origin' ? 0.062 : (n.fn ? 0.044 : 0.048)) * Math.pow(1 - r2, 0.48));
      const isSel = n.key === selKey;
      const ring = isSel ? '<circle cx="' + x.toFixed(4) + '" cy="' + y.toFixed(4) + '" r="' + (rad + 0.02).toFixed(4) + '" fill="none" stroke="#fde68a" stroke-width="0.007"/>' : '';
      const badge = n.fn ? '[' + n.fn + ']' : (n.key === 'origin' ? '★' : '●');
      const esc = String(n.label || '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
      const lbl = (Math.sqrt(r2) < 0.56 || isSel) ? '<text x="' + x.toFixed(4) + '" y="' + (y - rad - 0.015).toFixed(4) + '" text-anchor="middle" fill="#e2e8f0" font-size="0.034" font-weight="600" pointer-events="none">' + (esc.length > 28 ? esc.slice(0, 27) + '…' : esc) + '</text>' : '';
      out.push('<g data-node-key="' + n.key + '" style="cursor:pointer">' + ring +
        '<circle cx="' + x.toFixed(4) + '" cy="' + y.toFixed(4) + '" r="' + rad.toFixed(4) + '" fill="' + n.color + '" stroke="#f8fafc" stroke-width="0.0045"></circle>' +
        '<text x="' + x.toFixed(4) + '" y="' + (y + 0.012).toFixed(4) + '" text-anchor="middle" fill="#fff" font-size="0.034" font-weight="700" pointer-events="none">' + badge + '</text>' +
        lbl + '</g>');
    });
    svg.innerHTML = out.join('');
  }

  function updateInspector() {
    const n = byKey[selKey] || nodes[0];
    if (!n) return;
    document.getElementById('selShell').textContent = n.shell + ' · ' + n.kindLabel;
    document.getElementById('selPosture').textContent = n.posture;
    document.getElementById('selReff').textContent = 'r_eff = ' + n.rEff.toFixed(2);
    document.getElementById('selTitle').textContent = (n.fn ? '[' + n.fn + '] ' : '') + n.label;
    document.getElementById('selBody').textContent = n.body + (n.extra ? '\\n\\n' + n.extra : '');
  }

  function zoomTo(key) {
    if (!byKey[key]) return;
    selKey = key;
    const [fx, fy] = disp[key];
    const start = Object.assign({}, disp), end = {};
    nodes.forEach(n => { end[n.key] = mobius(start[n.key][0], start[n.key][1], fx, fy); });
    const t0 = performance.now(), dur = 240;
    function step(now) {
      const t = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - t, 3);
      nodes.forEach(n => { disp[n.key] = [start[n.key][0] + (end[n.key][0] - start[n.key][0]) * e, start[n.key][1] + (end[n.key][1] - start[n.key][1]) * e]; });
      draw();
      if (t < 1) requestAnimationFrame(step);
      else updateInspector();
    }
    requestAnimationFrame(step);
  }

  document.getElementById('gpmSvg').addEventListener('click', e => {
    const g = e.target.closest('[data-node-key]');
    if (g) zoomTo(g.getAttribute('data-node-key'));
  });
  document.getElementById('resetBtn').addEventListener('click', () => {
    nodes.forEach(n => { disp[n.key] = [n.zx, n.zy]; });
    selKey = (nodes[0] && nodes[0].key) || 'origin';
    draw();
    updateInspector();
  });
  const listEl = document.getElementById('nodeList');
  listEl.innerHTML = nodes.filter(n => n.shell !== 'Sector Hub').map(n => {
    const esc = String(n.label || '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
    return '<div class="node-row" data-list-key="' + n.key + '"><div><b>' + (n.fn ? '[' + n.fn + '] ' : '★ ') + esc + '</b><div style="font-size:11.5px;color:#94a3b8">' + n.shell + ' · ' + n.posture + '</div></div><span class="pill">r=' + n.rEff.toFixed(2) + '</span></div>';
  }).join('');
  listEl.addEventListener('click', e => {
    const r = e.target.closest('[data-list-key]');
    if (r) zoomTo(r.getAttribute('data-list-key'));
  });
  draw();
  updateInspector();
})();
</script>
</body>
</html>\n`;
}

/**
 * Write the Executive HTML/Markdown report(s) AND automatically emit the companion
 * Interactive Gandalf Poincaré Map Supplement (`<stem>-poincare-map.html`).
 */
export function writeExecutiveReportBundle(gradedOutput, { htmlPath = null, mdPath = null, poincareHtmlPath = null, title = null, subject = null, date = null } = {}) {
  const anchorReport = htmlPath || mdPath;
  if (!anchorReport && !poincareHtmlPath) return null;
  const suppAbs = resolve(poincareHtmlPath || derivePoincareSupplementPath(anchorReport));
  const backHref = htmlPath ? `./${basename(resolve(htmlPath))}` : null;
  writeTarget(
    suppAbs,
    renderGandalfPoincareSupplementHtml(gradedOutput, { title, subject, date, reportBackHref: backHref })
  );
  const suppHref = `./${basename(suppAbs)}`;
  const meta = { title, subject, date, supplementHref: suppHref };
  if (htmlPath) {
    writeTarget(htmlPath, renderExecutiveHtml(gradedOutput, meta));
  }
  if (mdPath) {
    writeTarget(mdPath, renderExecutiveMarkdown(gradedOutput, meta));
  }
  return suppAbs;
}

/** Parse CLI arguments for standalone report rendering. */
export function parseRenderArgs(argv) {
  const opts = {
    input: null,
    html: null,
    md: null,
    poincare_html: null,
    title: null,
    subject: null,
    date: null,
    help: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--input' || a === '-i') {
      opts.input = argv[++i];
      if (opts.input === undefined) throw new Error('--input requires a file path');
    } else if (a === '--html') {
      opts.html = argv[++i];
      if (opts.html === undefined) throw new Error('--html requires an output file path');
    } else if (a === '--md') {
      opts.md = argv[++i];
      if (opts.md === undefined) throw new Error('--md requires an output file path');
    } else if (a === '--poincare-html') {
      opts.poincare_html = argv[++i];
      if (opts.poincare_html === undefined) throw new Error('--poincare-html requires an output file path');
    } else if (a === '--title') {
      opts.title = argv[++i];
      if (opts.title === undefined) throw new Error('--title requires a string');
    } else if (a === '--subject') {
      opts.subject = argv[++i];
      if (opts.subject === undefined) throw new Error('--subject requires a string');
    } else if (a === '--date') {
      opts.date = argv[++i];
      if (opts.date === undefined) throw new Error('--date requires a string');
    } else if (a === '--help' || a === '-h') {
      opts.help = true;
    } else {
      throw new Error(`unknown argument ${JSON.stringify(a)}`);
    }
  }
  return opts;
}

function writeTarget(filePath, content) {
  const abs = resolve(filePath);
  mkdirSync(dirname(abs), { recursive: true });
  writeFileSync(abs, content, 'utf8');
}

export function main(argv = process.argv.slice(2)) {
  let opts;
  try {
    opts = parseRenderArgs(argv);
  } catch (err) {
    process.stderr.write(`render-report: ${err.message}\n${USAGE}\n`);
    process.exitCode = 2;
    return;
  }
  if (opts.help) {
    process.stdout.write(`${USAGE}\n`);
    return;
  }

  let rawText;
  try {
    rawText = opts.input ? readFileSync(opts.input, 'utf8') : readFileSync(0, 'utf8');
  } catch (err) {
    process.stderr.write(`render-report: could not read input: ${err.message}\n`);
    process.exitCode = 2;
    return;
  }

  let graded;
  try {
    graded = JSON.parse(rawText);
  } catch (err) {
    process.stderr.write(`render-report: input is not valid JSON: ${err.message}\n`);
    process.exitCode = 1;
    return;
  }

  const meta = { title: opts.title, subject: opts.subject, date: opts.date };
  try {
    if (opts.html || opts.md || opts.poincare_html) {
      writeExecutiveReportBundle(graded, {
        htmlPath: opts.html,
        mdPath: opts.md,
        poincareHtmlPath: opts.poincare_html,
        title: opts.title,
        subject: opts.subject,
        date: opts.date,
      });
    } else {
      process.stdout.write(renderExecutiveMarkdown(graded, meta));
    }
  } catch (err) {
    process.stderr.write(`render-report: failed to render report: ${err.message}\n`);
    process.exitCode = 1;
  }
}

function invokedDirectly() {
  const entry = process.argv[1];
  if (!entry) return false;
  try {
    const canon = (p) => {
      const abs = resolve(p);
      let real = abs;
      try {
        real = realpathSync(abs);
      } catch {
        /* virtual path */
      }
      return process.platform === 'win32' ? real.toLowerCase() : real;
    };
    return canon(fileURLToPath(import.meta.url)) === canon(entry);
  } catch {
    return false;
  }
}

if (invokedDirectly()) {
  main();
}
