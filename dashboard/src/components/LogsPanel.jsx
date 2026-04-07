import React from 'react';
import { ChevronDown, Terminal } from 'lucide-react';

/**
 * Collapsible live log panel.
 *
 * @param {{
 *   logs: string[],
 *   visible: boolean,
 *   onToggle: () => void,
 *   maxHeightClass?: string,
 *   showWaiting?: boolean,
 * }} props
 */
export default function LogsPanel({
  logs,
  visible,
  onToggle,
  maxHeightClass = 'max-h-64',
  showWaiting = false,
}) {
  return (
    <div className="rounded-2xl bg-[#0f0f13] border border-white/5 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full px-5 py-3 flex items-center justify-between hover:bg-white/[0.02] transition-all"
      >
        <span className="text-xs font-medium text-zinc-500 flex items-center gap-2">
          <Terminal size={13} /> Live Logs
        </span>
        <ChevronDown
          size={14}
          className={`text-zinc-600 transition-transform ${visible ? '' : 'rotate-180'}`}
        />
      </button>
      {visible && (
        <div
          className={`border-t border-white/5 p-5 ${maxHeightClass} overflow-y-auto font-mono text-[11px] space-y-1.5 text-zinc-500 leading-relaxed`}
        >
          {logs.map((log, i) => (
            <div
              key={i}
              className={`flex gap-3 ${log.toLowerCase().includes('error') ? 'text-red-400' : ''} ${
                log.startsWith('   ✅') || log.startsWith('✅') ? 'text-emerald-400' : ''
              }`}
            >
              <span className="text-zinc-700 shrink-0 select-none">
                [{new Date().toLocaleTimeString()}]
              </span>
              <span className="break-words">{log}</span>
            </div>
          ))}
          {showWaiting && (
            <div className="animate-pulse text-blue-400 font-medium">Waiting for output...</div>
          )}
        </div>
      )}
    </div>
  );
}
