// src/components/equipment/LogbookPanel.tsx
// Gap 1: Digital maintenance logbook UI
// Shows recent log entries + form to add new ones
// Used in CopilotChat sidebar and EquipmentHealth detail drawer

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { BookOpen, Plus, Clock, X, CheckCircle } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { logbookApi, type LogEntry } from '../../api/client';
import { useAuthStore } from '../../store';
import { formatDistanceToNow } from 'date-fns';

const LOG_TYPES = [
  { value: 'observation', label: 'Observation', color: 'text-blue-400' },
  { value: 'inspection',  label: 'Inspection',  color: 'text-green-400' },
  { value: 'repair',      label: 'Repair',      color: 'text-orange-400' },
  { value: 'measurement', label: 'Measurement', color: 'text-purple-400' },
  { value: 'anomaly_note',label: 'Anomaly Note',color: 'text-red-400' },
];

function LogEntryRow({ entry }: { entry: LogEntry }) {
  const typeColor = LOG_TYPES.find(t => t.value === entry.log_type)?.color ?? 'text-gray-400';
  return (
    <div className="border-b border-gray-800 last:border-0 py-2.5 px-1">
      <div className="flex items-center gap-2 mb-1">
        <span className={clsx('text-[10px] font-medium uppercase tracking-wide', typeColor)}>
          {entry.log_type}
        </span>
        <span className="text-[10px] text-gray-500">·</span>
        <span className="text-[10px] text-gray-500">{entry.logged_by}</span>
        <span className="text-[10px] text-gray-600 ml-auto">
          {formatDistanceToNow(new Date(entry.created_at), { addSuffix: true })}
        </span>
      </div>
      <p className="text-xs text-gray-300 leading-relaxed">{entry.notes}</p>
      {entry.work_order_id && (
        <p className="text-[10px] text-gray-500 mt-1">WO: {entry.work_order_id}</p>
      )}
    </div>
  );
}

interface LogbookPanelProps {
  equipmentId: string;
  compact?: boolean; // compact=true for sidebar, false for full view
}

export default function LogbookPanel({ equipmentId, compact = false }: LogbookPanelProps) {
  const { user } = useAuthStore();
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [notes, setNotes] = useState('');
  const [logType, setLogType] = useState('observation');

  const { data: logs, isLoading } = useQuery({
    queryKey: ['logbook', equipmentId],
    queryFn: () => logbookApi.list(equipmentId, compact ? 5 : 20),
    enabled: !!equipmentId,
    refetchInterval: 60_000,
  });

  const addMutation = useMutation({
    mutationFn: () => logbookApi.add(equipmentId, {
      logged_by:    user?.user_id ?? 'unknown',
      log_type:     logType,
      notes:        notes.trim(),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['logbook', equipmentId] });
      toast.success('Log entry added');
      setNotes('');
      setShowForm(false);
    },
    onError: () => toast.error('Failed to add log entry'),
  });

  return (
    <div className={clsx('bg-gray-900 border border-gray-800 rounded-xl overflow-hidden', compact && 'text-sm')}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <BookOpen size={14} className="text-gray-400" />
          <span className="text-xs font-medium text-gray-300">Maintenance Logbook</span>
          {logs && (
            <span className="text-[10px] text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded-full">
              {logs.length}
            </span>
          )}
        </div>
        <button
          onClick={() => setShowForm(v => !v)}
          className="flex items-center gap-1 text-[11px] px-2 py-1 bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 border border-blue-500/30 rounded-md transition-colors"
        >
          {showForm ? <X size={11} /> : <Plus size={11} />}
          {showForm ? 'Cancel' : 'Add entry'}
        </button>
      </div>

      {/* Add form */}
      {showForm && (
        <div className="px-4 py-3 border-b border-gray-800 bg-gray-800/40 space-y-2">
          <div className="flex gap-2 flex-wrap">
            {LOG_TYPES.map(t => (
              <button
                key={t.value}
                onClick={() => setLogType(t.value)}
                className={clsx(
                  'text-[10px] px-2 py-1 rounded border transition-colors',
                  logType === t.value
                    ? 'bg-blue-600 border-blue-500 text-white'
                    : 'border-gray-700 text-gray-400 hover:text-white'
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
          <textarea
            className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-200 placeholder-gray-500 resize-none focus:outline-none focus:border-blue-500"
            rows={3}
            placeholder="Enter observation, measurement, or finding…"
            value={notes}
            onChange={e => setNotes(e.target.value)}
          />
          <button
            disabled={!notes.trim() || addMutation.isPending}
            onClick={() => addMutation.mutate()}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg transition-colors"
          >
            <CheckCircle size={12} />
            {addMutation.isPending ? 'Saving…' : 'Save log entry'}
          </button>
        </div>
      )}

      {/* Log entries */}
      <div className={clsx('overflow-y-auto px-3', compact ? 'max-h-48' : 'max-h-80')}>
        {isLoading ? (
          <div className="flex items-center justify-center py-6 text-gray-500 text-xs">
            <Clock size={14} className="animate-spin mr-2" /> Loading…
          </div>
        ) : !logs || logs.length === 0 ? (
          <div className="text-center py-6 text-xs text-gray-500">
            <BookOpen size={20} className="mx-auto mb-2 opacity-40" />
            No log entries yet. Add the first observation.
          </div>
        ) : (
          logs.map(entry => <LogEntryRow key={entry.id} entry={entry} />)
        )}
      </div>
    </div>
  );
}
