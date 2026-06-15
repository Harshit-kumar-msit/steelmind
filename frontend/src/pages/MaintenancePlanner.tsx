// src/pages/MaintenancePlanner.tsx
import { useState }          from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Calendar, Plus, CheckCircle, Clock, AlertTriangle, RefreshCw } from 'lucide-react';
import clsx                  from 'clsx';
import toast                 from 'react-hot-toast';
import { workOrdersApi }     from '../api/client';
import type { WorkOrder }    from '../types';
import { format }            from 'date-fns';

const PRIORITY_COLOR: Record<string, string> = {
  P1: 'border-red-500/50 bg-red-500/5 text-red-400',
  P2: 'border-orange-500/50 bg-orange-500/5 text-orange-400',
  P3: 'border-yellow-500/50 bg-yellow-500/5 text-yellow-400',
  P4: 'border-gray-600 bg-gray-800/50 text-gray-400',
};
const STATUS_COLOR: Record<string, string> = {
  open:        'text-blue-400 bg-blue-500/10',
  in_progress: 'text-yellow-400 bg-yellow-500/10',
  completed:   'text-green-400 bg-green-500/10',
  draft:       'text-gray-400 bg-gray-700',
  cancelled:   'text-gray-500 bg-gray-800',
};

function WOCard({ wo, onStatusChange }: { wo: WorkOrder; onStatusChange: (code: string, status: string) => void }) {
  return (
    <div className={clsx('border rounded-xl p-4 space-y-3', PRIORITY_COLOR[wo.priority])}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-bold">{wo.priority}</span>
            <span className="text-xs text-gray-500 font-mono">{wo.wo_code}</span>
            {wo.ai_generated && (
              <span className="text-[10px] px-1.5 py-0.5 bg-blue-500/10 text-blue-400 border border-blue-500/30 rounded font-medium">AI</span>
            )}
          </div>
          <p className="text-sm font-medium text-white leading-tight">{wo.title}</p>
          <p className="text-xs text-gray-400 mt-0.5">{wo.equipment_id} · {wo.wo_type}</p>
        </div>
        <span className={clsx('text-xs px-2 py-0.5 rounded font-medium flex-shrink-0', STATUS_COLOR[wo.status] ?? 'text-gray-400 bg-gray-700')}>
          {wo.status.replace('_', ' ')}
        </span>
      </div>

      {/* Tasks */}
      {wo.tasks.length > 0 && (
        <ul className="space-y-1">
          {wo.tasks.slice(0, 3).map((task, i) => (
            <li key={i} className="flex items-center gap-2 text-xs text-gray-300">
              <span className="w-1 h-1 rounded-full bg-gray-500 flex-shrink-0" />{task}
            </li>
          ))}
          {wo.tasks.length > 3 && (
            <li className="text-xs text-gray-500">+{wo.tasks.length - 3} more tasks</li>
          )}
        </ul>
      )}

      <div className="flex items-center justify-between pt-1">
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span className="flex items-center gap-1">
            <Clock size={11} />{wo.estimated_hours}h est.
          </span>
          {wo.scheduled_date && (
            <span className="flex items-center gap-1">
              <Calendar size={11} />{format(new Date(wo.scheduled_date), 'dd MMM')}
            </span>
          )}
        </div>
        <div className="flex gap-1.5">
          {wo.status === 'open' && (
            <button
              onClick={() => onStatusChange(wo.wo_code, 'in_progress')}
              className="text-xs px-2 py-1 bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 rounded transition-colors"
            >
              Start
            </button>
          )}
          {wo.status === 'in_progress' && (
            <button
              onClick={() => onStatusChange(wo.wo_code, 'completed')}
              className="text-xs px-2 py-1 bg-green-600/20 hover:bg-green-600/30 text-green-400 rounded transition-colors"
            >
              Complete
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function MaintenancePlanner() {
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState('open');

  const { data: workOrders, isLoading } = useQuery({
    queryKey:        ['workorders', statusFilter],
    queryFn:         () => workOrdersApi.list({ status: statusFilter || undefined }),
    refetchInterval: 60_000,
  });

  const statusMutation = useMutation({
    mutationFn: ({ code, status }: { code: string; status: string }) =>
      workOrdersApi.updateStatus(code, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workorders'] });
      toast.success('Work order updated');
    },
  });

  const byPriority = (wos: WorkOrder[] = []) => ({
    P1: wos.filter((w) => w.priority === 'P1'),
    P2: wos.filter((w) => w.priority === 'P2'),
    P3: wos.filter((w) => w.priority === 'P3'),
    P4: wos.filter((w) => w.priority === 'P4'),
  });

  const grouped = byPriority(workOrders);
  const totalHours = (workOrders ?? []).reduce((s, w) => s + (w.estimated_hours ?? 0), 0);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Maintenance Planner</h1>
          <p className="text-sm text-gray-400 mt-0.5">
            {workOrders?.length ?? 0} work orders · {totalHours.toFixed(1)}h estimated
          </p>
        </div>
        <div className="flex gap-2">
          {['open', 'in_progress', 'completed', ''].map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={clsx(
                'text-xs px-3 py-1.5 rounded-lg transition-colors',
                statusFilter === s ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white',
              )}
            >
              {s || 'All'}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16 text-gray-400">
          <RefreshCw size={20} className="animate-spin mr-3" />Loading work orders…
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
          {(['P1', 'P2', 'P3', 'P4'] as const).map((p) => (
            <div key={p} className="space-y-3">
              <div className="flex items-center gap-2 pb-2 border-b border-gray-800">
                <span className={clsx('text-xs font-bold px-2 py-0.5 rounded', PRIORITY_COLOR[p])}>{p}</span>
                <span className="text-xs text-gray-500">{grouped[p].length} orders</span>
              </div>
              {grouped[p].map((wo) => (
                <WOCard
                  key={wo.id}
                  wo={wo}
                  onStatusChange={(code, status) => statusMutation.mutate({ code, status })}
                />
              ))}
              {grouped[p].length === 0 && (
                <p className="text-xs text-gray-600 text-center py-4">No {p} work orders</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
