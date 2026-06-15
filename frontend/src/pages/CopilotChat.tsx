// src/pages/CopilotChat.tsx
// Agentic Copilot UI — handles tool_call/tool_result SSE events from
// the ReAct loop, shows AgentThinking progress, streams final answer.

import { useEffect, useRef, useState, KeyboardEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Send, Bot, User, RefreshCw, FileText, Zap, X, BookOpen } from 'lucide-react';
import clsx from 'clsx';
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
      <button
        onClick={() => setOpen(v => !v)}
        className={clsx(
          'inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded border font-medium',
          color
        )}
      >
        <FileText size={10} />
        {citation.title.slice(0, 28)}
        {citation.title.length > 28 ? '…' : ''}
      </button>

      {open && (
        <div className="absolute bottom-full mb-1 left-0 z-50 w-72 bg-gray-800 border border-gray-700 rounded-lg p-3 shadow-xl">
          <div className="flex items-start justify-between mb-1">
            <p className="text-xs font-semibold text-white">{citation.title}</p>
            <button onClick={() => setOpen(false)}>
              <X size={12} className="text-gray-400" />
            </button>
          </div>
          <p className="text-xs text-gray-300 leading-relaxed">{citation.preview}</p>
          <p className="text-[10px] text-gray-500 mt-2 uppercase">
            {citation.category} · rank #{citation.rank}
          </p>
        </div>
      )}
    </div>
  );
}

// ── Action button ─────────────────────────────────────────────────────────────
function ActionBtn({
  action,
  onExecute,
}: {
  action: ActionButton;
  onExecute: (a: ActionButton) => void;
}) {
  const colors: Record<string, string> = {
    create_wo: 'bg-blue-600 hover:bg-blue-500',
    check_parts: 'bg-emerald-600 hover:bg-emerald-500',
    ack_alert: 'bg-yellow-600 hover:bg-yellow-500',
    add_log: 'bg-indigo-600 hover:bg-indigo-500',
    open_planner: 'bg-gray-600 hover:bg-gray-500',
  };

  return (
    <button
      onClick={() => onExecute(action)}
      className={clsx(
        'text-xs px-3 py-1.5 rounded-md text-white font-medium transition-colors flex items-center gap-1.5',
        colors[action.action_type] ?? 'bg-gray-700'
      )}
    >
      <Zap size={12} />
      {action.label}
    </button>
  );
}

// ── Message bubble ────────────────────────────────────────────────────────────
function MessageBubble({
  message,
  msgIndex,
  onActionExecute,
  sessionId,
  focusedEqId,
}: {
  message: any;
  msgIndex: number;
  onActionExecute: (a: ActionButton) => void;
  sessionId: string;
  focusedEqId: string;
}) {
  const isUser = message.role === 'user';

  function renderContent(text: string, citations: Citation[]) {
    const map = Object.fromEntries(
      citations.map((c: Citation) => [c.chunk_id, c])
    );

    return text.split(/(\[DOC:[^\]]+\])/g).map((part, i) => {
      const m = part.match(/^\[DOC:([^\]]+)\]$/);

      if (m) {
        const cit = map[m[1]];
        return cit ? (
          <CitationChip key={i} citation={cit} />
        ) : (
          <span key={i} className="text-xs text-gray-500">
            [src]
          </span>
        );
      }

      return <span key={i}>{part}</span>;
    });
  }

  return (
    <div className={clsx('flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
      <div
        className={clsx(
          'w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5',
          isUser ? 'bg-blue-600' : 'bg-gray-700'
        )}
      >
        {isUser ? (
          <User size={14} className="text-white" />
        ) : (
          <Bot size={14} className="text-blue-400" />
        )}
      </div>

      <div className={clsx('max-w-[80%] space-y-1.5', isUser ? 'items-end' : 'items-start')}>
        <div
          className={clsx(
            'rounded-2xl px-4 py-3 text-sm leading-relaxed',
            isUser
              ? 'bg-blue-600 text-white rounded-tr-none'
              : 'bg-gray-800 text-gray-100 rounded-tl-none border border-gray-700'
          )}
        >
          {message.isStreaming && !message.content ? (
            <div className="flex gap-1 items-center py-1">
              {[0, 150, 300].map(d => (
                <div
                  key={d}
                  className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                  style={{ animationDelay: `${d}ms` }}
                />
              ))}
            </div>
          ) : (
            <div className="whitespace-pre-wrap break-words">
              {renderContent(message.content, message.citations)}
            </div>
          )}
        </div>

        {!isUser && message.citations?.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-1">
            {message.citations.map((c: Citation) => (
              <CitationChip key={c.chunk_id} citation={c} />
            ))}
          </div>
        )}

        {!isUser && message.actions?.length > 0 && (
          <div className="flex flex-wrap gap-2 px-1">
            {message.actions.map((a: ActionButton, i: number) => (
              <ActionBtn key={i} action={a} onExecute={onActionExecute} />
            ))}
          </div>
        )}

        {!isUser && !message.isStreaming && message.content && (
          <div className="px-1">
            <FeedbackButtons
              sessionId={sessionId}
              messageIndex={msgIndex}
              equipmentId={focusedEqId}
              userQuery=""
              aiResponse={message.content}
              intent=""
            />
          </div>
        )}
      </div>
    </div>
  );
}

// ── Equipment panel ───────────────────────────────────────────────────────────
function EquipmentPanel({ equipmentId }: { equipmentId: string }) {
  const { data: eq } = useQuery({
    queryKey: ['equipment', equipmentId],
    queryFn: () => equipmentApi.get(equipmentId),
    enabled: !!equipmentId,
    refetchInterval: 30000,
  });

  const [showLog, setShowLog] = useState(false);
  if (!eq) return null;

  const sc = (s: number | null) =>
    (s ?? 0) >= 80
      ? 'text-red-400'
      : (s ?? 0) >= 60
      ? 'text-orange-400'
      : (s ?? 0) >= 40
      ? 'text-yellow-400'
      : 'text-green-400';

  return (
    <div className="w-64 flex-shrink-0 bg-gray-900 border-l border-gray-800 overflow-y-auto">
      <div className="p-4 space-y-3">
        <p className="text-[10px] text-gray-400 uppercase tracking-wide font-medium">
          Equipment context
        </p>

        <div>
          <p className="text-xs text-gray-500">ID</p>
          <p className="text-sm font-mono font-bold text-white">{eq.equipment_id}</p>
        </div>

        <div>
          <p className="text-xs text-gray-500">Name</p>
          <p className="text-xs text-gray-200">{eq.name}</p>
        </div>
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────
export default function CopilotChat() {
  const [searchParams] = useSearchParams();
  const initialEqId = searchParams.get('eq') ?? '';

  const {
    sessionId,
    messages,
    isStreaming,
    setFocusedEquipment,
    addUserMessage,
    startAssistantMessage,
    appendToken,
    finalizeMessage,
    clearMessages,
  } = useChatStore();

  const { user } = useAuthStore();

  const [input, setInput] = useState('');
  const [eqId, setEqId] = useState(initialEqId);

  const bottomRef = useRef<HTMLDivElement>(null);
  const activeEsRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (initialEqId) setFocusedEquipment(initialEqId);
  }, [initialEqId, setFocusedEquipment]);

  const sendMessage = (text?: string) => {
    const msg = (text ?? input).trim();
    if (!msg || isStreaming) return;

    setInput('');
    addUserMessage(msg);

    const aId = startAssistantMessage();
    activeEsRef.current?.close();

    const es = chatApi.stream(
      sessionId,
      msg,
      eqId,
      user?.user_id ?? 'engineer',
      (token) => appendToken(aId, token),

      // FIXED TYPES ↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓
      (citations: Citation[]) =>
        useChatStore.setState((s) => ({
          messages: s.messages.map((m) =>
            m.id === aId ? { ...m, citations: citations as Citation[] } : m
          ),
        })),

      (actions: ActionButton[]) =>
        useChatStore.setState((s) => ({
          messages: s.messages.map((m) =>
            m.id === aId ? { ...m, actions: actions as ActionButton[] } : m
          ),
        })),

      (_intent) => finalizeMessage(aId, [], []),

      (err) => {
        console.error(err);
        finalizeMessage(aId, [], []);
        toast.error('Stream error — retry');
      }
    );

    activeEsRef.current = es;
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleAction = async (action: ActionButton) => {
    try {
      if (action.action_type === 'create_wo') {
        await workOrdersApi.create(action.payload);
        toast.success('Work order created');
      } else if (action.action_type === 'ack_alert') {
        await alertsApi.acknowledge(action.payload.alert_id, user?.user_id ?? 'engineer');
        toast.success('Alert acknowledged');
      }
    } catch {
      toast.error('Action failed');
    }
  };

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col bg-gray-950">
        <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5">
          {messages.map((msg, idx) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              msgIndex={idx}
              onActionExecute={handleAction}
              sessionId={sessionId}
              focusedEqId={eqId}
            />
          ))}
          <div ref={bottomRef} />
        </div>

        <div className="p-4 border-t border-gray-800">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            className="w-full p-3 bg-gray-800 text-white rounded"
            placeholder="Ask something..."
          />
        </div>
      </div>

      {eqId && <EquipmentPanel equipmentId={eqId} />}
    </div>
  );
}