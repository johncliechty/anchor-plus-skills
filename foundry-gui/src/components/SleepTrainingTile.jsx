import React, { useState, useEffect } from 'react';

// Derive the skill's directory name (under the foundry skills root) from the
// manifest entry: basename of `source`, else the name slugified.
const skillDirName = (skill) => {
  if (!skill) return '';
  const source = skill.source || '';
  const base = source.split(/[\\/]/).filter(Boolean).pop();
  if (base) return base;
  return (skill.name || '').toLowerCase().trim().replace(/\s+/g, '-');
};

const shortSha = (sha) => (sha ? String(sha).slice(0, 10) : '?');

const gateLabel = (gate) => {
  if (!gate) return 'not recorded';
  const pass = gate.pass ?? '?';
  const fail = gate.fail ?? '?';
  return `${gate.ok ? 'GREEN' : 'RED'} · pass ${pass} / fail ${fail}`;
};

export default function SleepTrainingTile({ selectedSkill, summary, metrics }) {
  const [isExpanded, setIsExpanded] = useState(false);

  // The real sleep-session flow (propose → apply-on-branch → rollback),
  // backed by /api/foundry/sleep_session/* which spawns the REAL kernel CLI.
  // runState: idle | proposing | proposed | applying | applied | rollingBack | rolledBack | error
  const [runState, setRunState] = useState('idle');
  const [proposal, setProposal] = useState(null); // the kernel's propose response
  const [applyResult, setApplyResult] = useState(null); // the kernel's apply record
  const [rollbackResult, setRollbackResult] = useState(null); // the kernel's rollback record
  const [runError, setRunError] = useState(null); // { message, stderr }

  const skillId = skillDirName(selectedSkill);

  // Selecting another skill resets the flow — a proposal belongs to one skill.
  useEffect(() => {
    setRunState('idle');
    setProposal(null);
    setApplyResult(null);
    setRollbackResult(null);
    setRunError(null);
  }, [skillId]);

  const postJson = async (url, body) => {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    let data = null;
    try {
      data = await res.json();
    } catch (e) {
      data = { error: `HTTP ${res.status} — response was not JSON` };
    }
    return { res, data };
  };

  const runPropose = async () => {
    setRunState('proposing');
    setRunError(null);
    setProposal(null);
    setApplyResult(null);
    setRollbackResult(null);
    try {
      const { res, data } = await postJson('/api/foundry/sleep_session/propose', { skill: skillId });
      if (!res.ok || data.error) {
        setRunError({ message: data.error || `HTTP ${res.status}`, stderr: data.stderr || '' });
        setRunState('error');
        return;
      }
      setProposal(data);
      setRunState('proposed');
    } catch (err) {
      setRunError({ message: String(err), stderr: '' });
      setRunState('error');
    }
  };

  const runApply = async () => {
    if (!proposal || !proposal.proposalDir) return;
    setRunState('applying');
    setRunError(null);
    try {
      const { res, data } = await postJson('/api/foundry/sleep_session/apply', {
        proposalPath: proposal.proposalDir,
        confirm: true
      });
      setApplyResult(data);
      if (res.ok && data.outcome === 'applied') {
        setRunState('applied');
      } else {
        // refused / blocked (gate regressed → kernel auto-rolled-back) / error —
        // all real kernel records, shown honestly.
        setRunError({
          message: data.reason || data.error || `apply outcome: ${data.outcome || `HTTP ${res.status}`}`,
          stderr: data.stderr || ''
        });
        setRunState('error');
      }
    } catch (err) {
      setRunError({ message: String(err), stderr: '' });
      setRunState('error');
    }
  };

  const runRollback = async () => {
    if (!proposal || !proposal.proposalDir) return;
    setRunState('rollingBack');
    setRunError(null);
    try {
      const { res, data } = await postJson('/api/foundry/sleep_session/rollback', {
        proposalPath: proposal.proposalDir
      });
      setRollbackResult(data);
      if (res.ok && data.outcome === 'restored') {
        setRunState('rolledBack');
      } else {
        setRunError({
          message: data.error || `rollback outcome: ${data.outcome || `HTTP ${res.status}`}`,
          stderr: data.stderr || ''
        });
        setRunState('error');
      }
    } catch (err) {
      setRunError({ message: String(err), stderr: '' });
      setRunState('error');
    }
  };

  const discardProposal = () => {
    setRunState('idle');
    setProposal(null);
    setApplyResult(null);
    setRollbackResult(null);
    setRunError(null);
  };

  const formatTime = (timestamp) => {
    try {
      const date = new Date(timestamp);
      return date.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
    } catch (e) {
      return 'Unknown date';
    }
  };

  const getRelativeTime = (timestamp) => {
    try {
      const now = Date.now();
      const diffMs = now - timestamp;
      const diffMins = Math.floor(diffMs / 60000);

      if (diffMins < 1) return 'Just now';
      if (diffMins < 60) return `${diffMins}m ago`;

      const diffHours = Math.floor(diffMins / 60);
      if (diffHours < 24) return `${diffHours}h ago`;

      return `${Math.floor(diffHours / 24)}d ago`;
    } catch (e) {
      return '';
    }
  };

  // REAL data only: the selected skill's journal sessions (the training feed)
  // and the global sleep-run count (proposal artifacts on disk).
  const sessions = selectedSkill?.timeline || [];
  const journalCount = selectedSkill?.journalCount ?? sessions.length;
  const sleepRuns = metrics?.sleepRuns ?? 0;

  const busy = runState === 'proposing' || runState === 'applying' || runState === 'rollingBack';
  const noJournal = journalCount === 0;
  const units = proposal?.proposal?.units || [];
  const refused = proposal?.proposal?.refused || [];
  const baseline = proposal?.proposal?.baseline;

  return (
    <div className={`panel expandable-tile ${isExpanded ? 'expanded' : ''} shrink-0 transition-all duration-300`} id="tile-st">
      {/* Header */}
      <div
        className="p-6 flex justify-between items-center cursor-pointer hover:bg-[#0A0A0F]/80 transition-colors h-[80px]"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-900 border border-slate-800 text-[#00F0FF]">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z" />
            </svg>
          </div>
          <div>
            <h3 className="text-sm font-bold uppercase tracking-widest text-slate-400 group-hover:text-white font-display">Sleep console</h3>
            <p className="text-[10px] text-slate-500 font-mono mt-0.5">Journal sessions &rarr; gated improvements</p>
          </div>
        </div>
        <button
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#16161A] text-slate-400 hover:text-white transition-all duration-200"
          onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded); }}
          aria-label="Toggle Sleep & Training"
        >
          <svg className={`w-4 h-4 chevron ${isExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="px-6 pb-6 pt-6 border-t border-[#16161A] bg-black/40 space-y-6">

          {/* Section 1: Training feed */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-[9px] uppercase font-bold tracking-widest text-[#00F0FF] font-mono">Training Feed</span>
              {journalCount > 0 && (
                <span className="text-[10px] text-slate-500 font-mono">
                  {journalCount} journal session{journalCount === 1 ? '' : 's'} &middot; all queued for the next sleep run
                </span>
              )}
            </div>

            {sessions.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-850 p-6 text-center">
                <p className="text-xs text-slate-500">No journal sessions captured for this skill yet.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {sessions.map((entry, index) => {
                  const relativeTime = getRelativeTime(entry.timestamp);
                  return (
                    <div
                      key={index}
                      className="rounded-xl border bg-slate-900/10 border-slate-900 hover:border-slate-800 transition-all duration-200 p-4 flex items-start justify-between gap-4"
                    >
                      <div className="space-y-1 overflow-hidden">
                        <span className="text-xs font-semibold tracking-wide text-slate-200 block truncate">
                          {entry.event}
                        </span>
                        <div className="flex items-center gap-2 text-[10px] text-slate-500 font-mono">
                          <span>{formatTime(entry.timestamp)}</span>
                          {relativeTime && (
                            <>
                              <span>&bull;</span>
                              <span>{relativeTime}</span>
                            </>
                          )}
                        </div>
                      </div>
                      <span
                        className="text-[9px] font-medium px-2 py-0.5 rounded border shrink-0 text-amber-400 bg-amber-950/20 border-amber-900/30 tracking-wider"
                        title="awaiting the first sleep session"
                      >
                        QUEUED
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Section 2: Sleep runs — the REAL kernel loop */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-[9px] uppercase font-bold tracking-widest text-[#00F0FF] font-mono">Sleep Runs</span>
              <span className="text-[10px] text-slate-500 font-mono">{sleepRuns} run{sleepRuns === 1 ? '' : 's'}</span>
            </div>

            {/* Run sleep session — spawns the real kernel propose */}
            <div className="mb-4">
              <button
                onClick={runPropose}
                disabled={busy || noJournal || !skillId}
                className={`w-full py-3 rounded-lg text-xs font-bold uppercase tracking-widest transition-all duration-300 flex justify-center items-center gap-2 font-display border ${
                  busy || noJournal || !skillId
                    ? 'bg-[#0A0A0F] text-slate-600 border-slate-900 cursor-not-allowed'
                    : 'bg-[#16161A] hover:bg-[#00F0FF] hover:text-black text-[#00F0FF] border-[#00F0FF]/20 hover:border-[#00F0FF]/50 shadow-[0_0_15px_rgba(0,240,255,0.05)]'
                }`}
              >
                {runState === 'proposing' ? (
                  <>
                    <span className="w-3 h-3 rounded-full border-2 border-[#00F0FF]/30 border-t-[#00F0FF] animate-spin" />
                    Proposing&hellip; (distill + frozen gate)
                  </>
                ) : (
                  <>Run sleep session{skillId ? ` — ${skillId}` : ''}</>
                )}
              </button>
              {noJournal && (
                <p className="text-[10px] text-slate-600 font-mono mt-2 text-center">
                  needs journal sessions to distill &mdash; this skill has none yet
                </p>
              )}
            </div>

            {/* Error state — the real stderr, never swallowed */}
            {runState === 'error' && runError && (
              <div className="rounded-xl border border-rose-900/40 bg-rose-950/10 p-4 mb-4 space-y-2">
                <span className="text-[9px] uppercase font-bold tracking-widest text-rose-400 font-mono block">
                  Sleep session {applyResult && applyResult.outcome ? applyResult.outcome.toUpperCase() : 'ERROR'}
                </span>
                <p className="text-xs text-rose-300 font-mono break-all">{runError.message}</p>
                {runError.stderr && (
                  <pre className="text-[10px] text-rose-400/70 font-mono whitespace-pre-wrap max-h-[140px] overflow-y-auto bg-black/40 rounded p-2 border border-rose-900/20">{runError.stderr}</pre>
                )}
                <button
                  onClick={discardProposal}
                  className="text-[9px] uppercase tracking-wider font-bold text-slate-400 hover:text-white px-2.5 py-1 rounded bg-slate-950 border border-slate-900 transition-colors"
                >
                  Dismiss
                </button>
              </div>
            )}

            {/* The REAL proposal (not yet applied) */}
            {(runState === 'proposed' || runState === 'applying') && proposal && (
              <div className="rounded-xl border border-[#00F0FF]/30 bg-[#00F0FF]/[0.03] p-4 mb-4 space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-[9px] uppercase font-bold tracking-widest text-[#00F0FF] font-mono">
                    Proposal (not yet applied)
                  </span>
                  <span className="text-[10px] text-slate-500 font-mono">
                    {proposal.unitCount} unit{proposal.unitCount === 1 ? '' : 's'} &middot; {proposal.refusedCount} refused
                  </span>
                </div>

                {/* Frozen baseline + eval-gate plan */}
                <div className="space-y-1 text-[10px] font-mono">
                  <div className="text-slate-400">
                    <span className="text-slate-600">Frozen baseline SHA:</span>{' '}
                    <span title={baseline?.sha}>{shortSha(baseline?.sha)}</span>
                  </div>
                  <div className="text-slate-400 break-all">
                    <span className="text-slate-600">Eval gate (frozen):</span>{' '}
                    {proposal.proposal?.eval_gate?.command || 'unknown'}
                  </div>
                  <div className="text-slate-400">
                    <span className="text-slate-600">Gate before-results:</span>{' '}
                    <span className={baseline?.gateBefore?.ok ? 'text-emerald-400' : 'text-rose-400'}>
                      {gateLabel(baseline?.gateBefore)}
                    </span>
                  </div>
                </div>

                {/* Candidate lessons + concrete diffs */}
                {units.length === 0 ? (
                  <p className="text-xs text-slate-500">
                    The distiller produced no applyable units from this journal (nothing corroborated across contexts yet).
                  </p>
                ) : (
                  <div className="space-y-3">
                    {units.map((unit, idx) => (
                      <div key={idx} className="rounded-lg border border-slate-900 bg-black/40 p-3 space-y-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-semibold text-slate-200 truncate" title={unit.situation}>
                            {unit.situation}
                          </span>
                          <span className="text-[9px] font-mono text-slate-500 shrink-0" title="provenance class">
                            {unit.class}
                          </span>
                        </div>
                        <div className="text-[10px] text-slate-500 font-mono">
                          {unit.genuineSupport} genuine run(s) across {(unit.contexts || []).length} context(s) &middot; slug <span className="text-slate-400">{unit.slug}</span>
                        </div>
                        {unit.diffText && (
                          <pre className="text-[10px] font-mono whitespace-pre-wrap max-h-[160px] overflow-y-auto bg-[#050507] rounded p-2 border border-[#16161A] text-slate-400">{unit.diffText}</pre>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {refused.length > 0 && (
                  <div className="text-[10px] font-mono text-amber-500/80 space-y-0.5">
                    {refused.map((r, idx) => (
                      <div key={idx}>refused {r.slug}: {r.reason}</div>
                    ))}
                  </div>
                )}

                {/* Approve / Discard */}
                <div className="flex items-center gap-3 pt-1">
                  <button
                    onClick={runApply}
                    disabled={busy || units.length === 0}
                    className={`flex-1 py-2.5 rounded-lg text-[10px] font-bold uppercase tracking-widest transition-all duration-300 border font-display flex justify-center items-center gap-2 ${
                      busy || units.length === 0
                        ? 'bg-[#0A0A0F] text-slate-600 border-slate-900 cursor-not-allowed'
                        : 'bg-[#00F0FF]/10 hover:bg-[#00F0FF] hover:text-black text-[#00F0FF] border-[#00F0FF]/30'
                    }`}
                  >
                    {runState === 'applying' ? (
                      <>
                        <span className="w-3 h-3 rounded-full border-2 border-[#00F0FF]/30 border-t-[#00F0FF] animate-spin" />
                        Applying on branch&hellip; (gate + regression)
                      </>
                    ) : (
                      <>Approve &mdash; apply on branch</>
                    )}
                  </button>
                  <button
                    onClick={discardProposal}
                    disabled={busy}
                    className="px-4 py-2.5 rounded-lg text-[10px] font-bold uppercase tracking-widest text-slate-400 hover:text-white bg-slate-950 border border-slate-900 transition-colors font-display"
                  >
                    Discard
                  </button>
                </div>
              </div>
            )}

            {/* Applied — the real branch + gate result, with rollback */}
            {(runState === 'applied' || runState === 'rollingBack') && applyResult && (
              <div className="rounded-xl border border-emerald-900/40 bg-emerald-950/10 p-4 mb-4 space-y-3">
                <span className="text-[9px] uppercase font-bold tracking-widest text-emerald-400 font-mono block">
                  Applied on branch (behind the frozen gate)
                </span>
                <div className="space-y-1 text-[10px] font-mono text-slate-400">
                  <div><span className="text-slate-600">Branch:</span> {applyResult.branch}</div>
                  <div>
                    <span className="text-slate-600">Promoted commit:</span>{' '}
                    <span title={applyResult.promotedCommit}>{shortSha(applyResult.promotedCommit)}</span>
                    {' '}<span className="text-slate-600">off baseline</span>{' '}
                    <span title={applyResult.baselineSha}>{shortSha(applyResult.baselineSha)}</span>
                  </div>
                  <div>
                    <span className="text-slate-600">Gate after apply:</span>{' '}
                    <span className={applyResult.frozen_benchmark_delta?.after?.ok ? 'text-emerald-400' : 'text-rose-400'}>
                      {gateLabel(applyResult.frozen_benchmark_delta?.after)}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-600">Regression test:</span>{' '}
                    <span className={applyResult.regression?.ok ? 'text-emerald-400' : 'text-rose-400'}>
                      {applyResult.regression?.ok ? 'PASS' : 'FAIL'}
                    </span>
                  </div>
                  {applyResult.journalEntry && (
                    <div className="break-all"><span className="text-slate-600">Promotion journal entry:</span> {applyResult.journalEntry}</div>
                  )}
                </div>
                <button
                  onClick={runRollback}
                  disabled={busy}
                  className={`w-full py-2.5 rounded-lg text-[10px] font-bold uppercase tracking-widest transition-all duration-300 border font-display flex justify-center items-center gap-2 ${
                    busy
                      ? 'bg-[#0A0A0F] text-slate-600 border-slate-900 cursor-not-allowed'
                      : 'bg-rose-950/20 hover:bg-rose-500 hover:text-black text-rose-400 border-rose-900/40'
                  }`}
                >
                  {runState === 'rollingBack' ? (
                    <>
                      <span className="w-3 h-3 rounded-full border-2 border-rose-400/30 border-t-rose-400 animate-spin" />
                      Rolling back&hellip;
                    </>
                  ) : (
                    <>Rollback &mdash; restore frozen baseline</>
                  )}
                </button>
              </div>
            )}

            {/* Rolled back — the real restore record */}
            {runState === 'rolledBack' && rollbackResult && (
              <div className="rounded-xl border border-slate-800 bg-slate-900/20 p-4 mb-4 space-y-2">
                <span className="text-[9px] uppercase font-bold tracking-widest text-slate-400 font-mono block">
                  Rolled back &mdash; frozen baseline restored
                </span>
                <div className="text-[10px] font-mono text-slate-400">
                  <span className="text-slate-600">Restored SHA:</span>{' '}
                  <span title={rollbackResult.restoredSha}>{shortSha(rollbackResult.restoredSha)}</span>
                  {' '}<span className="text-slate-600">(from</span>{' '}
                  <span title={rollbackResult.fromSha}>{shortSha(rollbackResult.fromSha)}</span><span className="text-slate-600">)</span>
                </div>
                <button
                  onClick={discardProposal}
                  className="text-[9px] uppercase tracking-wider font-bold text-slate-400 hover:text-white px-2.5 py-1 rounded bg-slate-950 border border-slate-900 transition-colors"
                >
                  Done
                </button>
              </div>
            )}

            {/* Run history summary (real artifact counts from the server) */}
            {runState === 'idle' && (
              sleepRuns === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-850 p-6 text-center space-y-2">
                  <p className="text-xs text-slate-500 leading-relaxed">
                    No sleep sessions have run yet. Click &ldquo;Run sleep session&rdquo; to distill this skill&rsquo;s journal into a test-gated proposal &mdash; nothing is applied without your approval.
                  </p>
                  {summary && (
                    <p className="text-[10px] text-slate-600 font-mono leading-relaxed">{summary}</p>
                  )}
                </div>
              ) : (
                <div className="rounded-xl border border-slate-900 bg-slate-900/10 p-4">
                  <p className="text-xs text-slate-400">
                    {sleepRuns} sleep run{sleepRuns === 1 ? '' : 's'} recorded (proposal artifacts under the server&rsquo;s sleep-runs directory).
                  </p>
                  {summary && (
                    <p className="text-[10px] text-slate-600 font-mono leading-relaxed mt-1">{summary}</p>
                  )}
                </div>
              )
            )}
          </div>

          {/* Footer: pipeline note */}
          <p className="text-[10px] text-slate-600 font-mono leading-relaxed border-t border-[#16161A] pt-4">
            Journals captured on every run &rarr; a sleep session distills them into a test-gated, human-approved improvement &rarr; applied on a branch.
          </p>
        </div>
      )}
    </div>
  );
}
