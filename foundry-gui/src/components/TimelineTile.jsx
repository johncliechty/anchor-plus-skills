import React, { useState } from 'react';

export default function TimelineTile({ timeline, selectedSkill }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [expandedIndices, setExpandedIndices] = useState({});

  const toggleExpand = (index) => {
    setExpandedIndices(prev => ({
      ...prev,
      [index]: !prev[index]
    }));
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

  // REAL data: the selected skill's journal-derived timeline (from /api/skills).
  // Falls back to the global timeline only when the skill carries none of its own.
  const events = selectedSkill?.timeline || (selectedSkill ? [] : (timeline || []));

  return (
    <div className={`panel expandable-tile ${isExpanded ? 'expanded' : ''} shrink-0 transition-all duration-300`} id="tile-eh">
      {/* Header */}
      <div 
        className="p-6 flex justify-between items-center cursor-pointer hover:bg-[#0A0A0F]/80 transition-colors h-[80px]" 
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-900 border border-slate-800 text-slate-400">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-5 h-5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <div>
            <h3 className="text-sm font-bold uppercase tracking-widest text-slate-400 group-hover:text-white font-display">3. Evolution History</h3>
            <p className="text-[10px] text-slate-500 font-mono mt-0.5">Journal sessions — the sleep-loop training feed</p>
          </div>
        </div>
        <button 
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#16161A] text-slate-400 hover:text-white transition-all duration-200"
          onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded); }}
          aria-label="Toggle Evolution History"
        >
          <svg className={`w-4 h-4 chevron ${isExpanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>

      {/* Expanded Content */}
      {isExpanded && (
        <div className="px-6 pb-6 pt-6 border-t border-[#16161A] bg-black/40">
          {events.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-850 p-6 text-center">
              <p className="text-xs text-slate-500">No journal entries recorded for this skill yet.</p>
            </div>
          ) : (
            <div className="relative pl-6 border-l border-slate-800 space-y-6 ml-3">
              {events.map((entry, index) => {
                const isSuccess = entry.status === 'success';
                const isItemExpanded = !!expandedIndices[index];
                const relativeTime = getRelativeTime(entry.timestamp);

                return (
                  <div key={index} className="relative group">
                    {/* Timeline marker */}
                    <span className={`absolute -left-[31px] top-1.5 flex h-4.5 w-4.5 items-center justify-center rounded-full border-2 bg-black transition-all duration-300 ${
                      isSuccess 
                        ? 'border-emerald-500/80 group-hover:border-emerald-400 group-hover:shadow-glow-success' 
                        : 'border-rose-500/80 group-hover:border-rose-400 group-hover:shadow-glow-failure'
                    }`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${isSuccess ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                    </span>

                    {/* Card container */}
                    <div 
                      className={`rounded-xl border transition-all duration-200 overflow-hidden cursor-pointer ${
                        isSuccess 
                          ? 'bg-slate-900/10 border-slate-900 hover:border-slate-800' 
                          : 'bg-rose-950/5 border-rose-950/20 hover:border-rose-900/20'
                      }`}
                      onClick={() => toggleExpand(index)}
                    >
                      {/* Header */}
                      <div className="p-4 flex items-start justify-between gap-4">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className={`text-xs font-semibold tracking-wide ${isSuccess ? 'text-slate-200' : 'text-rose-300'}`}>
                              {entry.event}
                            </span>
                            <span className={`text-[9px] font-medium px-2 py-0.2 rounded border ${
                              isSuccess 
                                ? 'text-emerald-450 bg-emerald-950/20 border-emerald-900/20' 
                                : 'text-rose-450 bg-rose-950/20 border-rose-900/20'
                            }`}>
                              {entry.status?.toUpperCase() || 'SUCCESS'}
                            </span>
                          </div>
                          <div className="flex items-center gap-2 text-[10px] text-slate-500 font-mono">
                            <span>{formatTime(entry.timestamp)}</span>
                            {relativeTime && (
                              <>
                                <span>•</span>
                                <span>{relativeTime}</span>
                              </>
                            )}
                          </div>
                        </div>

                        <button 
                          className="flex h-6 w-6 items-center justify-center rounded bg-slate-900 border border-slate-800 text-slate-400 transition-colors"
                          aria-label="Expand Timeline Event"
                        >
                          <svg 
                            xmlns="http://www.w3.org/2000/svg" 
                            fill="none" 
                            viewBox="0 0 24 24" 
                            strokeWidth={2} 
                            stroke="currentColor" 
                            className={`h-3 w-3 transition-transform duration-200 ${isItemExpanded ? 'rotate-180' : ''}`}
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                          </svg>
                        </button>
                      </div>

                      {/* Details */}
                      {isItemExpanded && (
                        <div className="p-4 bg-[#050507] border-t border-slate-900">
                          <div className="space-y-1">
                            <span className="text-[9px] text-slate-500 uppercase tracking-wider font-semibold block">Commit Log Details:</span>
                            <p className="text-xs text-slate-350 font-mono leading-relaxed whitespace-pre-wrap">
                              {entry.details || "No details available."}
                            </p>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
