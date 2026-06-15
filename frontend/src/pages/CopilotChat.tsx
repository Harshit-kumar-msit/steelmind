// src/pages/CopilotChat.tsx
// Agentic Copilot UI — handles tool_call/tool_result SSE events from
// the ReAct loop, shows AgentThinking progress, streams final answer.
import { useEffect, useRef, useState, KeyboardEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Send, Bot, User, RefreshCw, FileText, Zap, X, BookOpen } from 'lucide-react';
import clsx from 'clsx';
import { v4 as uuidv4 } from 'uuid';
import toast from 'react-hot-toast';
import { useChatStore, useAuthStore } from '../store';
import { chatApi, equipmentApi, workOrdersApi, alertsApi, logbookApi } from '../api/client';
import type { Citation, ActionButton } from '../types';
import FeedbackButtons from '../components/copilot/FeedbackButtons';
import LogbookPanel from '../components/equipment/LogbookPanel';
import AgentThinking, { type ToolEvent } from '../components/copilot/AgentThinking';

// ── Citation chip ─────────────────────────────────────────────────────────────
function CitationChip({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false);
  const catColors: Record<string, string> = {
    manual: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    sop: 'bg-green-500/10 text-green-400 border-green-500/30',
    rca: 'bg-orange-500/10 text-orange-400 border-orange-500/30',
    standard: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
    default: 'bg-gray-500/10 text-gray-400 border-gray-500/30',
  };
  const color = catColors[citation.category] ?? catColors.default;
  return (
    <div className="relative inline-block">
      <button onClick={() => setOpen(v => !v)} className={clsx('inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded border font-medium', color)}>
        <FileText size={10} />{citation.title.slice(0, 28)}{citation.title.length > 28 ? '…' : ''}
      </button>
      {open && (
        <div className="absolute bottom-full mb-1 left-0 z-50 w-72 bg-gray-800 border border-gray-700 rounded-lg p-3 shadow-xl">
          <div className="flex items-start justify-between mb-1">
            <p className="text-xs font-semibold text-white">{citation.title}</p>
            <button onClick={() => setOpen(false)}><X size={12} className="text-gray-400" /></button>
          </div>
          <p className="text-xs text-gray-300 leading-relaxed">{citation.preview}</p>
          <p className="text-[10px] text-gray-500 mt-2 uppercase">{citation.category} · rank #{citation.rank}</p>
        </div>
      )}
    </div>
  );
}

// ── Action button ─────────────────────────────────────────────────────────────
function ActionBtn({ action, onExecute }: { action: ActionButton; onExecute: (a: ActionButton) => void }) {
  const colors: Record<string, string> = {
    create_wo: 'bg-blue-600 hover:bg-blue-500',
    check_parts: 'bg-emerald-600 hover:bg-emerald-500',
    ack_alert: 'bg-yellow-600 hover:bg-yellow-500',
    add_log: 'bg-indigo-600 hover:bg-indigo-500',
    open_planner: 'bg-gray-600 hover:bg-gray-500',
  };
  return (
    <button onClick={() => onExecute(action)} className={clsx('text-xs px-3 py-1.5 rounded-md text-white font-medium transition-colors flex items-center gap-1.5', colors[action.action_type] ?? 'bg-gray-700')}>
      <Zap size={12} />{action.label}
    </button>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────
function MessageBubble({ message, msgIndex, onActionExecute, sessionId, focusedEqId }:
  { message: any; msgIndex: number; onActionExecute: (a: ActionButton) => void; sessionId: string; focusedEqId: string }) {
  const isUser = message.role === 'user';
  function renderContent(text: string, citations: Citation[]) {
    const map = Object.fromEntries(citations.map((c: Citation) => [c.chunk_id, c]));
    return text.split(/(\[DOC:[^\]]+\])/g).map((part, i) => {
      const m = part.match(/^\[DOC:([^\]]+)\]$/);
      if (m) { const cit = map[m[1]]; return cit ? <CitationChip key={i} citation={cit} /> : <span key={i} className="text-xs text-gray-500">[src]</span>; }
      return <span key={i}>{part}</span>;
    });
  }
  return (
    <div className={clsx('flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
      <div className={clsx('w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5', isUser ? 'bg-blue-600' : 'bg-gray-700')}>
        {isUser ? <User size={14} className="text-white" /> : <Bot size={14} className="text-blue-400" />}
      </div>
      <div className={clsx('max-w-[80%] space-y-1.5', isUser ? 'items-end' : 'items-start')}>
        <div className={clsx('rounded-2xl px-4 py-3 text-sm leading-relaxed', isUser ? 'bg-blue-600 text-white rounded-tr-none' : 'bg-gray-800 text-gray-100 rounded-tl-none border border-gray-700')}>
          {message.isStreaming && !message.content ? (
            <div className="flex gap-1 items-center py-1">
              {[0, 150, 300].map(d => <div key={d} className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: `${d}ms` }} />)}
            </div>
          ) : (
            <div className="whitespace-pre-wrap break-words">{renderContent(message.content, message.citations)}</div>
          )}
          {message.isStreaming && message.content && <span className="inline-block w-0.5 h-4 bg-blue-400 animate-pulse ml-0.5 align-middle" />}
        </div>
        {!isUser && message.citations?.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-1">{message.citations.map((c: Citation) => <CitationChip key={c.chunk_id} citation={c} />)}</div>
        )}
        {!isUser && message.actions?.length > 0 && (
          <div className="flex flex-wrap gap-2 px-1">{message.actions.map((a: ActionButton, i: number) => <ActionBtn key={i} action={a} onExecute={onActionExecute} />)}</div>
        )}
        {!isUser && !message.isStreaming && message.content && (
          <div className="px-1">
            <FeedbackButtons sessionId={sessionId} messageIndex={msgIndex} equipmentId={focusedEqId} userQuery="" aiResponse={message.content} intent="" />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Equipment context panel ───────────────────────────────────────────────────
function EquipmentPanel({ equipmentId }: { equipmentId: string }) {
  const { data: eq } = useQuery({ queryKey: ['equipment', equipmentId], queryFn: () => equipmentApi.get(equipmentId), enabled: !!equipmentId, refetchInterval: 30_000 });
  const [showLog, setShowLog] = useState(false);
  if (!eq) return null;
  const sc = (s: number | null) => (s ?? 0) >= 80 ? 'text-red-400' : (s ?? 0) >= 60 ? 'text-orange-400' : (s ?? 0) >= 40 ? 'text-yellow-400' : 'text-green-400';
  return (
    <div className="w-64 flex-shrink-0 bg-gray-900 border-l border-gray-800 overflow-y-auto">
      <div className="p-4 space-y-3">
        <p className="text-[10px] text-gray-400 uppercase tracking-wide font-medium">Equipment context</p>
        <div><p className="text-xs text-gray-500">ID</p><p className="text-sm font-mono font-bold text-white">{eq.equipment_id}</p></div>
        <div><p className="text-xs text-gray-500">Name</p><p className="text-xs text-gray-200 leading-relaxed">{eq.name}</p></div>
        <div className="grid grid-cols-2 gap-2">
          {([['Priority', eq.priority_score], ['RUL (d)', eq.rul_days], ['Anomaly', eq.anomaly_score], ['Class', eq.criticality]] as [string, number | string | null][]).map(([label, val]) => (
            <div key={label} className="bg-gray-800 rounded-lg p-2">
              <p className="text-[10px] text-gray-500">{label}</p>
              <p className={clsx('text-lg font-bold', typeof val === 'number' ? sc(val) : 'text-white')}>{typeof val === 'number' ? val?.toFixed(0) ?? '—' : val}</p>
            </div>
          ))}
        </div>
        {eq.open_alerts?.length > 0 && (
          <div>
            <p className="text-[10px] text-gray-500 mb-1.5">Open alerts ({eq.open_alerts.length})</p>
            {eq.open_alerts.slice(0, 3).map((a: any) => (
              <div key={a.id} className={clsx('text-xs px-2 py-1.5 rounded border mb-1.5', a.severity === 'critical' ? 'border-red-500/30 bg-red-500/10 text-red-300' : 'border-yellow-500/30 bg-yellow-500/10 text-yellow-300')}>
                {a.title.slice(0, 45)}
              </div>
            ))}
          </div>
        )}
        <button onClick={() => setShowLog(v => !v)} className="flex items-center gap-2 w-full text-xs text-gray-400 hover:text-white py-1.5 transition-colors">
          <BookOpen size={13} />{showLog ? 'Hide logbook' : 'Show logbook'}
        </button>
      </div>
      {showLog && <div className="px-3 pb-4"><LogbookPanel equipmentId={eq.equipment_id} compact /></div>}
    </div>
  );
}

const SUGGESTED_PROMPTS = [
  'What is causing the current anomaly on this equipment?',
  'Should I shut down the blower now or can it wait?',
  'Plan the maintenance window for this Saturday',
  'Do we have all the parts needed for a bearing replacement?',
  'Run a root cause analysis on the latest failure',
  'What does the ISO standard say about these vibration levels?',
];

// ── Main page ─────────────────────────────────────────────────────────────────
export default function CopilotChat() {
  const [searchParams] = useSearchParams();
  const initialEqId = searchParams.get('eq') ?? '';
  const { sessionId, messages, isStreaming, setFocusedEquipment, addUserMessage, startAssistantMessage, appendToken, finalizeMessage, clearMessages } = useChatStore();
  const { user } = useAuthStore();
  const [input, setInput]           = useState('');
  const [eqId, setEqId]             = useState(initialEqId);
  const [toolEvents, setToolEvents] = useState<ToolEvent[]>([]);
  const bottomRef                   = useRef<HTMLDivElement>(null);
  const inputRef                    = useRef<HTMLTextAreaElement>(null);
  const activeEsRef                 = useRef<EventSource | null>(null);

  useEffect(() => { if (initialEqId) setFocusedEquipment(initialEqId); }, [initialEqId, setFocusedEquipment]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, toolEvents]);
  useEffect(() => () => activeEsRef.current?.close(), []);

  const sendMessage = (text?: string) => {
    const msg = (text ?? input).trim();
    if (!msg || isStreaming) return;
    setInput('');
    setToolEvents([]);  // reset tool events for new turn
    addUserMessage(msg);
    const aId = startAssistantMessage();
    activeEsRef.current?.close();

    const es = chatApi.stream(
      sessionId, msg, eqId, user?.user_id ?? 'engineer',
      (token) => appendToken(aId, token),
      (citations) => useChatStore.setState(s => ({ messages: s.messages.map(m => m.id === aId ? { ...m, citations } : m) })),
      (actions)   => useChatStore.setState(s => ({ messages: s.messages.map(m => m.id === aId ? { ...m, actions } : m) })),
      (_intent)   => { finalizeMessage(aId, [], []); setToolEvents([]); },
      (err)       => { console.error(err); finalizeMessage(aId, [], []); toast.error('Stream error — retry'); },
    );

    // Intercept raw SSE to catch tool_call / tool_result events
    // Override onmessage to handle agent tool events
    const originalOnMessage = es.onmessage;
    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'tool_call') {
          setToolEvents(prev => [...prev, { type: 'tool_call', name: data.name, status: 'calling', args: data.args }]);
          return; // don't pass tool events to the original handler
        }
        if (data.type === 'tool_result') {
          setToolEvents(prev => prev.map(e => e.name === data.name && e.status === 'calling' ? { ...e, status: data.ok ? 'done' : 'error' } : e));
          return;
        }
        if (data.type === 'done' && data.actions) {
          useChatStore.setState(s => ({ messages: s.messages.map(m => m.id === aId ? { ...m, actions: data.actions } : m) }));
          finalizeMessage(aId, [], []);
          setToolEvents([]);
          es.close();
          return;
        }
      } catch { /* pass through */ }
      // Pass all other events (token, citations, done) to original handler
      if (originalOnMessage) originalOnMessage.call(es, event);
    };

    activeEsRef.current = es;
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };

  const handleAction = async (action: ActionButton) => {
    try {
      if (action.action_type === 'create_wo') {
        await workOrdersApi.create({ equipment_id: action.payload.equipment_id ?? eqId, title: action.payload.title ?? 'AI-generated work order', priority: (action.payload.priority as any) ?? 'P2', wo_type: 'predictive', ai_generated: true, tasks: action.payload.tasks?.split(',') ?? [] });
        toast.success('Work order created');
      } else if (action.action_type === 'check_parts') {
        sendMessage(`Check parts availability for: ${action.payload.part_ids ?? 'required parts'}`);
      } else if (action.action_type === 'ack_alert') {
        await alertsApi.acknowledge(action.payload.alert_id, user?.user_id ?? 'engineer');
        toast.success('Alert acknowledged');
      } else if (action.action_type === 'add_log' && eqId && action.payload.notes) {
        await logbookApi.add(eqId, { logged_by: user?.user_id ?? 'engineer', log_type: action.payload.log_type ?? 'observation', notes: action.payload.notes });
        toast.success('Observation logged');
      }
    } catch { toast.error('Action failed'); }
  };

  return (
    <div className="flex h-full gap-0 -m-6 overflow-hidden" style={{ height: 'calc(100vh - 56px)' }}>
      <div className="flex-1 flex flex-col bg-gray-950 min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800 bg-gray-900 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-blue-600/20 border border-blue-500/30 flex items-center justify-center">
              <Bot size={16} className="text-blue-400" />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">SteelMind AI Copilot</p>
              <p className="text-xs text-gray-400">
                {isStreaming
                  ? toolEvents.length > 0
                    ? <span className="text-blue-400">Agent calling {toolEvents.filter(e => e.status === 'calling').length} tool(s)…</span>
                    : <span className="text-blue-400">Thinking…</span>
                  : 'Agentic · Llama 3.3 70B · Groq function-calling'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input className="text-xs bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-gray-300 w-36 focus:outline-none focus:border-blue-500" placeholder="Equipment ID…" value={eqId} onChange={e => setEqId(e.target.value)} />
            <button onClick={clearMessages} className="text-xs px-3 py-1.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-gray-400 transition-colors">New chat</button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center pb-20">
              <div className="w-14 h-14 rounded-2xl bg-blue-600/20 border border-blue-500/30 flex items-center justify-center mb-4">
                <Bot size={24} className="text-blue-400" />
              </div>
              <h2 className="text-lg font-bold text-white mb-2">SteelMind Agentic Copilot</h2>
              <p className="text-sm text-gray-400 max-w-md mb-2 leading-relaxed">
                Ask anything. I'll autonomously fetch the data I need — anomaly scores, spare parts,
                maintenance logs, RUL estimates — then give you a grounded answer.
              </p>
              <p className="text-xs text-gray-600 mb-8">Powered by Groq function-calling · Llama 3.3 70B · ReAct loop</p>
              <div className="grid grid-cols-2 gap-2 max-w-xl w-full">
                {SUGGESTED_PROMPTS.map(prompt => (
                  <button key={prompt} onClick={() => sendMessage(prompt)} className="text-left text-xs px-3 py-2.5 bg-gray-800 hover:bg-gray-700 border border-gray-700 rounded-lg text-gray-300 transition-colors leading-relaxed">{prompt}</button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, idx) => (
            <MessageBubble key={msg.id} message={msg} msgIndex={idx} onActionExecute={handleAction} sessionId={sessionId} focusedEqId={eqId} />
          ))}

          {/* Live agent tool-call progress — shown while streaming */}
          {isStreaming && toolEvents.length > 0 && (
            <div className="flex gap-3">
              <div className="w-8 h-8 rounded-full bg-gray-700 flex items-center justify-center flex-shrink-0">
                <Bot size={14} className="text-blue-400" />
              </div>
              <div className="flex-1">
                <AgentThinking events={toolEvents} isActive={isStreaming} />
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="flex-shrink-0 border-t border-gray-800 bg-gray-900 px-4 py-4">
          <div className="flex items-end gap-3 bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 focus-within:border-blue-500 transition-colors">
            <textarea
              ref={inputRef}
              className="flex-1 bg-transparent text-sm text-gray-100 placeholder-gray-500 resize-none outline-none max-h-32 leading-relaxed"
              placeholder={isStreaming ? 'Agent is working…' : eqId ? `Ask about ${eqId}…` : 'Ask anything — I\'ll fetch the data I need automatically'}
              rows={1}
              value={input}
              disabled={isStreaming}
              onChange={e => { setInput(e.target.value); e.target.style.height = 'auto'; e.target.style.height = `${Math.min(e.target.scrollHeight, 128)}px`; }}
              onKeyDown={handleKeyDown}
            />
            <button onClick={() => sendMessage()} disabled={isStreaming || !input.trim()} className={clsx('flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center transition-colors', !isStreaming && input.trim() ? 'bg-blue-600 hover:bg-blue-500 text-white' : 'bg-gray-700 text-gray-500 cursor-not-allowed')}>
              {isStreaming ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
            </button>
          </div>
          <p className="text-[10px] text-gray-600 mt-1.5 text-center">
            Agentic mode · Enter to send · Agent autonomously calls tools to fetch data before answering
          </p>
        </div>
      </div>

      {eqId && <EquipmentPanel equipmentId={eqId} />}
    </div>
  );
}
