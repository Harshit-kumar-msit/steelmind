// src/components/copilot/AgentThinking.tsx
// Shows live tool-call progress while the ReAct agent runs.
// SSE events: {type:"tool_call", name:"..."} and {type:"tool_result", name:"..."}
// This is the #1 demo differentiator vs a plain chatbot.

import { Activity, Database, Search, Package, Bell, ClipboardList, Plus, CheckCircle, Loader } from 'lucide-react';
import clsx from 'clsx';

export interface ToolEvent {
  type:   'tool_call' | 'tool_result' | 'error';
  name:   string;
  status: 'calling' | 'done' | 'error';
  args?:  Record<string, unknown>;
}

const TOOL_META: Record<string, { label: string; Icon: React.ElementType; color: string }> = {
  get_equipment_health:      { label: 'Fetching equipment health',    Icon: Activity,      color: 'text-blue-400' },
  get_anomaly_detail:        { label: 'Analysing anomaly sensors',    Icon: Activity,      color: 'text-red-400' },
  get_rul_breakdown:         { label: 'Computing RUL estimate',       Icon: Database,      color: 'text-orange-400' },
  check_spare_parts:         { label: 'Checking spare parts stock',   Icon: Package,       color: 'text-emerald-400' },
  get_open_alerts:           { label: 'Loading active alerts',        Icon: Bell,          color: 'text-yellow-400' },
  get_maintenance_logs:      { label: 'Reading maintenance logs',     Icon: ClipboardList, color: 'text-indigo-400' },
  get_work_orders:           { label: 'Fetching work orders',         Icon: ClipboardList, color: 'text-purple-400' },
  get_plant_priority_queue:  { label: 'Loading plant priority queue', Icon: Database,      color: 'text-cyan-400' },
  create_work_order:         { label: 'Creating work order',          Icon: Plus,          color: 'text-green-400' },
  add_maintenance_log:       { label: 'Logging observation',          Icon: Plus,          color: 'text-green-400' },
  search_knowledge_base:     { label: 'Searching knowledge base',     Icon: Search,        color: 'text-blue-300' },
};

interface AgentThinkingProps {
  events:   ToolEvent[];
  isActive: boolean;
}

export default function AgentThinking({ events, isActive }: AgentThinkingProps) {
  if (events.length === 0 && !isActive) return null;

  return (
    <div className="bg-gray-800/50 border border-gray-700 rounded-xl px-4 py-3 space-y-2 my-2">
      <div className="flex items-center gap-2 mb-1">
        <div className="w-5 h-5 rounded-full bg-blue-600/30 border border-blue-500/40 flex items-center justify-center">
          <Activity size={10} className="text-blue-400" />
        </div>
        <span className="text-[11px] font-medium text-blue-400 uppercase tracking-wide">
          Agent is reasoning…
        </span>
      </div>
      {events.map((event, i) => {
        const meta = TOOL_META[event.name] ?? { label: event.name, Icon: Database, color: 'text-gray-400' };
        return (
          <div key={i} className="flex items-center gap-2.5">
            {event.status === 'calling'
              ? <Loader size={12} className={clsx('animate-spin flex-shrink-0', meta.color)} />
              : event.status === 'error'
              ? <span className="text-red-400 text-xs flex-shrink-0">✗</span>
              : <CheckCircle size={12} className="text-green-400 flex-shrink-0" />}
            <meta.Icon size={12} className={clsx('flex-shrink-0', meta.color)} />
            <span className={clsx('text-xs', event.status === 'done' ? 'text-gray-400 line-through' : meta.color)}>
              {meta.label}
            </span>
          </div>
        );
      })}
      {isActive && events.length > 0 && events[events.length-1].status === 'done' && (
        <div className="flex items-center gap-2 pt-1">
          <Loader size={11} className="animate-spin text-gray-500" />
          <span className="text-xs text-gray-500">Synthesising answer…</span>
        </div>
      )}
    </div>
  );
}
