import React, { useEffect } from 'react';

// HONEST op modal — replaces the old CommandOverlay "creation engine" chat
// (which theatrically simulated a Gandalf/Crucible orchestrator). These two
// operations are REAL, but they live in Anchor's Python control plane
// (foundry_ops.py), confirm-token-gated through skill_runner — there is no
// sanctioned invocation path from this standalone node GUI. Until the GUI is
// folded into Anchor, this modal says exactly that instead of pretending.
const OPS = {
  scaffold_skill: {
    title: 'Create New Skill',
    op: 'foundry.scaffold_skill',
    what: 'Scaffolds a new skill on disk from the template (SKILL.md + North-Star stub + manifest + map-v2 registration + branch commit; refuses to overwrite an existing skill).',
    guiVerb: 'foundry_gui_write.create_skill'
  },
  edit_north_star: {
    title: 'Edit North Star',
    op: 'foundry.edit_north_star',
    what: 'The ONLY sanctioned per-skill North-Star mutation path: the PROPOSE leg parks a reviewable unified diff (the file is untouched); the APPLY leg spends an explicit confirm token to land it.',
    guiVerb: 'foundry_gui_write.north_star_propose / north_star_apply'
  }
};

export default function ControlPlaneModal({ op, onClose }) {
  const info = op ? OPS[op] : null;

  useEffect(() => {
    if (!info) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [info, onClose]);

  if (!info) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="panel w-full max-w-lg mx-6 rounded-2xl border border-[#16161A] bg-[#050507] shadow-[0_0_50px_rgba(0,0,0,0.9)]"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={info.title}
      >
        {/* Header */}
        <div className="h-14 border-b border-[#16161A] flex items-center justify-between px-6 bg-[#08080A] rounded-t-2xl">
          <span className="text-xs font-bold uppercase tracking-widest text-white font-display">{info.title}</span>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-white text-[9px] font-bold uppercase tracking-wider bg-[#16161A] border border-[#333]/30 px-2.5 py-1.5 rounded transition-all duration-200"
          >
            Close ✕
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4">
          <div className="rounded-xl border border-[#00F0FF]/20 bg-[#00F0FF]/[0.03] p-4">
            <span className="text-[9px] uppercase font-bold tracking-widest text-[#00F0FF] font-mono block mb-1.5">
              Control-plane op
            </span>
            <span className="text-sm font-mono text-white">{info.op}</span>
          </div>

          <p className="text-xs text-slate-400 leading-relaxed font-light">{info.what}</p>

          <div className="rounded-xl border border-amber-900/30 bg-amber-950/10 p-4 space-y-2">
            <span className="text-[9px] uppercase font-bold tracking-widest text-amber-400 font-mono block">
              Not wired from this GUI yet
            </span>
            <p className="text-[11px] text-slate-400 leading-relaxed font-light">
              This operation runs through Anchor&rsquo;s control plane — a confirm-token-gated,
              auto-journaled Python op (<span className="font-mono text-slate-300">{info.guiVerb}</span>{' '}
              &rarr; <span className="font-mono text-slate-300">foundry_ops.py</span>). This standalone
              GUI has no sanctioned invocation path to it; the wiring lands when the GUI is folded
              into Anchor. Until then, run it from the Anchor dashboard.
            </p>
          </div>

          <div className="text-[10px] font-mono text-slate-500 flex items-center gap-1.5 overflow-hidden">
            <span className="text-[#00F0FF] shrink-0">OP SOURCE:</span>
            <span className="truncate" title="C:/dev/Anchor-foundry-v2-wt/foundry_ops.py">
              C:/dev/Anchor-foundry-v2-wt/foundry_ops.py
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
