import React, { useState } from 'react';

export default function SummaryTile({ summary, metaRecipe }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const skills = metaRecipe?.skills || [];
  const systemPromptUpdates = metaRecipe?.systemPromptUpdates || [];
  const hasDetails = skills.length > 0 || systemPromptUpdates.length > 0;

  return (
    <div className="glass-panel glass-panel-hover rounded-2xl p-6 shadow-lg transition-all duration-300">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-800 text-slate-400">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="h-6 w-6">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 21l8.982-5.097a9.001 9.001 0 10-8.169-0.002z" />
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-semibold text-slate-200 tracking-wide">Last Synthesis Summary</h2>
              {skills.length > 0 && (
                <span className="text-[10px] font-medium text-emerald-400 bg-emerald-950/60 border border-emerald-900/50 px-2 py-0.5 rounded-full">
                  {skills.length} {skills.length === 1 ? 'skill' : 'skills'} updated
                </span>
              )}
            </div>
            <p className="text-xs text-slate-500">Overview of the last successful sleep cycle</p>
          </div>
        </div>
        {hasDetails && (
          <button 
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-800/50 hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-all duration-200"
            aria-label="Toggle Summary Details"
          >
            <svg 
              xmlns="http://www.w3.org/2000/svg" 
              fill="none" 
              viewBox="0 0 24 24" 
              strokeWidth={2} 
              stroke="currentColor" 
              className={`h-4 w-4 transition-transform duration-300 ${isExpanded ? 'rotate-180' : ''}`}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
            </svg>
          </button>
        )}
      </div>

      <div className="mt-4">
        <div className="rounded-xl bg-slate-950/60 p-4 border border-slate-800/50">
          <p className="text-sm leading-relaxed text-slate-300">
            {summary || "No synthesis has run yet. Wait for a sleep cycle to trigger."}
          </p>
        </div>
      </div>

      {hasDetails && (
        <div className={`transition-all duration-300 overflow-hidden ${isExpanded ? 'max-h-[800px] opacity-100 mt-4' : 'max-h-0 opacity-0'}`}>
          <div className="space-y-4 pt-2 border-t border-slate-800/60">
            {skills.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Skill Recipe Updates</h3>
                <div className="space-y-3">
                  {skills.map((skill, index) => (
                    <div key={index} className="rounded-lg bg-slate-950/40 p-3 border border-slate-900 text-xs">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="font-semibold text-slate-200 bg-slate-800/60 px-2 py-0.5 rounded border border-slate-700/40">{skill.name}</span>
                      </div>
                      
                      {skill.recipe && (
                        <div className="mt-1.5 text-slate-400 font-mono bg-slate-950/80 p-2 rounded border border-slate-800 max-h-[80px] overflow-y-auto">
                          {skill.recipe}
                        </div>
                      )}

                      {skill.changes && skill.changes.length > 0 && (
                        <div className="mt-2 space-y-1">
                          <span className="text-[10px] text-slate-500 font-medium">Changelog:</span>
                          <ul className="list-disc pl-4 space-y-0.5 text-slate-400">
                            {skill.changes.map((change, cIdx) => (
                              <li key={cIdx}>{change}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {systemPromptUpdates.length > 0 && (
              <div>
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 font-mono">System Prompt Instructions</h3>
                <ul className="rounded-lg bg-slate-950/40 p-3 border border-slate-900 space-y-1.5 list-none">
                  {systemPromptUpdates.map((update, index) => (
                    <li key={index} className="text-xs text-slate-400 flex items-start gap-2">
                      <span className="text-slate-600 mt-1 select-none">↳</span>
                      <span>{update}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
