import React, { useState } from 'react';
import Markdown from './Markdown.jsx';

export default function NorthStarTile({ selectedSkill, globalNorthStar, onEditNorthStar }) {
  const [isExpanded, setIsExpanded] = useState(true);

  const description = selectedSkill
    ? (selectedSkill.northStar || selectedSkill.description || globalNorthStar || '')
    : (globalNorthStar || '');
  // Prefer HUMAN.md path for people; fall back to SKILL.md
  const filePath = selectedSkill
    ? (selectedSkill.human_path || selectedSkill.file_path || 'HUMAN.md')
    : 'NORTH-STAR.md';
  const isHumanCard = Boolean(selectedSkill?.humanCard || selectedSkill?.human_path);

  return (
    <div className={`panel expandable-tile ${isExpanded ? 'expanded' : ''} shrink-0 transition-all duration-300`} id="tile-ns">
      {/* Header */}
      <div 
        className="p-6 flex justify-between items-center cursor-pointer hover:bg-[#0A0A0F]/80 transition-colors h-[80px]" 
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-900 border border-slate-800 text-[#00F0FF]">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499c.196-.396.768-.396.964 0l3.007 6.09 6.72 1.018c.44.066.617.61.3.923l-4.817 4.75 1.136 6.726c.075.446-.395.787-.79.57l-6.04-3.178-6.04 3.178c-.395.217-.865-.124-.79-.57l1.136-6.726-4.817-4.75c-.317-.313-.14-.857.3-1.018l6.72-1.018 3.007-6.09z" />
            </svg>
          </div>
          <div>
            <h3 className="text-sm font-bold uppercase tracking-widest text-[#00F0FF] font-display">1. North Star & Identity</h3>
            <p className="text-[10px] text-slate-500 font-mono mt-0.5">
              {isHumanCard ? 'Human skill card (HUMAN.md) — rendered for people' : 'Objective directive & file path'}
            </p>
          </div>
        </div>
        <button 
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#16161A] text-slate-400 hover:text-white transition-all duration-200"
          onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded); }}
          aria-label="Toggle North Star Details"
        >
          <svg className={`w-4 h-4 chevron ${isExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="px-6 pb-6 pt-4 border-t border-[#16161A] bg-black/40">
          <div className="rounded-xl bg-[#050507] p-5 border border-[#16161A]/60 max-h-[420px] overflow-y-auto">
            {description
              ? <Markdown source={description} />
              : <p className="text-sm text-slate-500">No North Star documented for this skill yet.</p>}
          </div>

          <div className="mt-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-3">
            <div className="text-[10px] font-mono text-slate-500 flex items-center gap-1.5 overflow-hidden w-full md:w-auto">
              <span className="text-[#00F0FF] shrink-0">URI:</span>
              <span className="truncate" title={filePath}>{filePath}</span>
            </div>
            
            <button
              onClick={onEditNorthStar}
              className="text-[10px] bg-[#16161A] hover:bg-[#00F0FF] hover:text-black text-slate-400 hover:text-slate-900 font-bold uppercase tracking-widest px-4 py-2 rounded-lg border border-[#333]/30 transition-all duration-300 shadow-[0_0_15px_rgba(0,240,255,0.02)]"
            >
              Edit North Star
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
