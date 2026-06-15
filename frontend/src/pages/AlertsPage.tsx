// src/pages/AlertsPage.tsx
// Purpose: Display all plant alerts with filtering, acknowledge, and resolve actions.
// Data source: GET /api/v1/alerts (polled every 30s)

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Bell, CheckCircle, Clock, Filter, RefreshCw, AlertTriangle, XCircle } from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import { alertsApi } from '../api/client';
import { useAuthStore } from '../store';
import type { Alert } from '../types';
import { formatDistanceToNow } from 'date-fns';

// ── Helpers ───────────────────────────────────────────────────────────────────

function SeverityIcon({ severity }: { severity: string }) {
  if (severity === 'critical') return <XCircle size={16} className="text-red-400" />;
  if (severity === 'warning')  return <AlertTriangle size={16} className="text-yellow-400" />;
  return <Bell size={16} className="text-blue-400" />;
}

function SeverityBadge({ severity }: { severity: string }) {
  const map: Record<string, string> = {
    critical: 'bg-red-500/10 text-red-400 border-red-500/30',
    warning:  'bg-yellow-500/10 text-yellow-400 border-yellow-500/30',
    info:     'bg-blue-500/10 text-blue-400 border-blue-500/30',
  };
  return (
    <span className={clsx('text-xs px-2 py-0.5 rounded border font-medium uppercase tracking-wide', map[severity] ?? map.info)}>
      {severity}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    open:         'bg-red-500/10 text-red-400',
    acknowledged: 'bg-yellow-500/10 text-yellow-400',
    resolved:     'bg-green-500/10 text-green-400',
  };
  return (
    <span className={clsx('text-xs px-2 py-0.5 rounded font-medium', map[status] ?? 'bg-gray-500/10 text-gray-400')}>
      {status}
    </span>
  );
}

// ── Alert Row ─────────────────────────────────────────────────────────────────

function AlertRow({
  alert,
  onAck,
  onResolve,
}: {
  alert: Alert;
  onAck:     (code: string) => void;
  onResolve: (code: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <tr
        onClick={() => setExpanded((v) => !v)}
        className={clsx(
          'border-b border-gray-800/50 cursor-pointer transition-colors',
          alert.severity === 'critical' ? 'hover:bg-red-950/20' : 'hover:bg-gray-800/40',
          expanded && 'bg-gray-800/30',
        )}
      >
        {/* Severity indicator strip */}
        <td className="w-1 p-0">
          <div
            className={clsx(
              'w-1 h-full min-h-[52px]',
              alert.severity === 'critical' ? 'bg-red-500' :
              alert.severity === 'warning'  ? 'bg-yellow-500' : 'bg-blue-500',
            )}
          />
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            <SeverityIcon severity={alert.severity} />
            <div>
              <p className="text-sm font-medium text-white leading-tight">{alert.title}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {alert.alert_code} · {alert.equipment_id}
              </p>
            </div>
          </div>
        </td>
        <td className="px-4 py-3"><SeverityBadge severity={alert.severity} /></td>
        <td className="px-4 py-3"><StatusBadge status={alert.status} /></td>
        <td className="px-4 py-3 text-xs text-gray-400 font-mono">
          {alert.anomaly_score != null ? `${alert.anomaly_score.toFixed(0)}/100` : '—'}
        </td>
        <td className="px-4 py-3 text-xs text-gray-400 font-mono">
          {alert.rul_days != null ? `${alert.rul_days.toFixed(0)}d` : '—'}
        </td>
        <td className="px-4 py-3 text-xs text-gray-500">
          {formatDistanceToNow(new Date(alert.created_at), { addSuffix: true })}
        </td>
        <td className="px-4 py-3">
          <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
            {alert.status === 'open' && (
              <button
                onClick={() => onAck(alert.alert_code)}
                className="text-xs px-2.5 py-1 bg-yellow-500/10 hover:bg-yellow-500/20 border border-yellow-500/30 text-yellow-400 rounded-md transition-colors"
              >
                Ack
              </button>
            )}
            {alert.status !== 'resolved' && (
              <button
                onClick={() => onResolve(alert.alert_code)}
                className="text-xs px-2.5 py-1 bg-green-500/10 hover:bg-green-500/20 border border-green-500/30 text-green-400 rounded-md transition-colors"
              >
                Resolve
              </button>
            )}
          </div>
        </td>
      </tr>

      {/* Expanded description row */}
      {expanded && (
        <tr className="bg-gray-800/20 border-b border-gray-800">
          <td />
          <td colSpan={7} className="px-6 py-3">
            <p className="text-sm text-gray-300 leading-relaxed">{alert.description}</p>
            {alert.acknowledged_at && (
              <p className="text-xs text-gray-500 mt-1">
                Acknowledged: {new Date(alert.acknowledged_at).toLocaleString()}
              </p>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function AlertsPage() {
  const { user }      = useAuthStore();
  const queryClient   = useQueryClient();

  // Filters
  const [severityFilter, setSeverityFilter] = useState('');
  const [statusFilter,   setStatusFilter]   = useState('open');

  const { data: alerts, isLoading, refetch } = useQuery({
    queryKey:        ['alerts', severityFilter, statusFilter],
    queryFn:         () => alertsApi.list({
                       severity: severityFilter || undefined,
                       status:   statusFilter   || undefined,
                     }),
    refetchInterval: 30_000,
  });

  const ackMutation = useMutation({
    mutationFn: (code: string) =>
      alertsApi.acknowledge(code, user?.user_id ?? 'engineer'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      toast.success('Alert acknowledged');
    },
    onError: () => toast.error('Failed to acknowledge'),
  });

  const resolveMutation = useMutation({
    mutationFn: (code: string) => alertsApi.resolve(code),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      toast.success('Alert resolved');
    },
    onError: () => toast.error('Failed to resolve'),
  });

  // Summary counts
  const allAlerts  = alerts ?? [];
  const critical   = allAlerts.filter((a) => a.severity === 'critical' && a.status === 'open').length;
  const warning    = allAlerts.filter((a) => a.severity === 'warning'  && a.status === 'open').length;
  const acked      = allAlerts.filter((a) => a.status === 'acknowledged').length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Alerts</h1>
          <p className="text-sm text-gray-400 mt-0.5">
            {allAlerts.length} alerts · {critical} critical · {warning} warnings
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="flex items-center gap-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm text-gray-300 transition-colors"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {/* Summary pills */}
      <div className="flex gap-3 flex-wrap">
        {[
          { label: `${critical} Critical`, color: 'border-red-500/40 text-red-400 bg-red-500/10' },
          { label: `${warning} Warning`,   color: 'border-yellow-500/40 text-yellow-400 bg-yellow-500/10' },
          { label: `${acked} Acknowledged`,color: 'border-yellow-500/30 text-yellow-300 bg-yellow-500/5' },
        ].map(({ label, color }) => (
          <span key={label} className={clsx('text-xs px-3 py-1.5 rounded-full border font-medium', color)}>
            {label}
          </span>
        ))}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-xl px-4 py-3">
        <Filter size={14} className="text-gray-400" />
        <span className="text-xs text-gray-400 font-medium">Filters:</span>

        {/* Status filter */}
        <div className="flex gap-1.5">
          {['', 'open', 'acknowledged', 'resolved'].map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={clsx(
                'text-xs px-3 py-1 rounded-md transition-colors',
                statusFilter === s
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-white',
              )}
            >
              {s || 'All status'}
            </button>
          ))}
        </div>

        <div className="w-px h-4 bg-gray-700" />

        {/* Severity filter */}
        <div className="flex gap-1.5">
          {['', 'critical', 'warning', 'info'].map((s) => (
            <button
              key={s}
              onClick={() => setSeverityFilter(s)}
              className={clsx(
                'text-xs px-3 py-1 rounded-md transition-colors',
                severityFilter === s
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:text-white',
              )}
            >
              {s || 'All severity'}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <RefreshCw size={20} className="animate-spin mr-3" /> Loading alerts…
          </div>
        ) : allAlerts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-gray-500">
            <CheckCircle size={32} className="mb-3 text-green-500/50" />
            <p className="text-sm font-medium">No alerts match the current filters</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-400 border-b border-gray-800">
                <th className="w-1" />
                <th className="text-left px-4 py-3 font-medium">Alert</th>
                <th className="text-left px-4 py-3 font-medium">Severity</th>
                <th className="text-left px-4 py-3 font-medium">Status</th>
                <th className="text-left px-4 py-3 font-medium">Anomaly</th>
                <th className="text-left px-4 py-3 font-medium">RUL</th>
                <th className="text-left px-4 py-3 font-medium">Age</th>
                <th className="text-left px-4 py-3 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {allAlerts.map((alert) => (
                <AlertRow
                  key={alert.id}
                  alert={alert}
                  onAck={(code) => ackMutation.mutate(code)}
                  onResolve={(code) => resolveMutation.mutate(code)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
