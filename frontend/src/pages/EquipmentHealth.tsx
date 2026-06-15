// src/pages/EquipmentHealth.tsx
import { useQuery } from '@tanstack/react-query';
import { equipmentApi } from '../api/client';
import { Activity, AlertTriangle, Clock, Zap, RefreshCw } from 'lucide-react';
import clsx from 'clsx';
import type { Equipment, PlantSummary } from '../types';
import { useUIStore } from '../store';
import { useNavigate } from 'react-router-dom';

// ── Helper Components ──────────────────────────────────────────────────────

function SummaryCard({ label, value, sub, color, Icon }: {
  label: string; value: string | number; sub?: string;
  color: 'blue' | 'yellow' | 'orange' | 'red'; Icon: React.ElementType;
}) {
  const colors = {
    blue:   'bg-blue-500/10 text-blue-400 border-blue-500/20',
    yellow: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
    orange: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
    red:    'bg-red-500/10 text-red-400 border-red-500/20',
  };
  return (
    <div className={clsx('rounded-xl border p-4', colors[color])}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium opacity-80">{label}</span>
        <Icon size={16} />
      </div>
      <p className="text-2xl font-bold">{value}</p>
      {sub && <p className="text-xs opacity-70 mt-1">{sub}</p>}
    </div>
  );
}

function PriorityBar({ score }: { score: number | null }) {
  const s = score ?? 0;
  const color = s >= 80 ? 'bg-red-500' : s >= 60 ? 'bg-orange-500' : s >= 40 ? 'bg-yellow-500' : 'bg-green-500';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div className={clsx('h-full rounded-full transition-all', color)} style={{ width: `${s}%` }} />
      </div>
      <span className="text-xs font-mono w-8 text-right text-gray-300">{s.toFixed(0)}</span>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    operational: 'bg-green-500/10 text-green-400',
    degraded:    'bg-yellow-500/10 text-yellow-400',
    warning:     'bg-orange-500/10 text-orange-400',
    critical:    'bg-red-500/10 text-red-400',
    offline:     'bg-gray-500/10 text-gray-400',
    maintenance: 'bg-blue-500/10 text-blue-400',
  };
  return (
    <span className={clsx('text-xs px-2 py-0.5 rounded-full font-medium', map[status] ?? map.offline)}>
      {status}
    </span>
  );
}

function CriticalityBadge({ level }: { level: string }) {
  const map: Record<string, string> = {
    A: 'text-red-400 border-red-500/40',
    B: 'text-yellow-400 border-yellow-500/40',
    C: 'text-gray-400 border-gray-500/40',
  };
  return (
    <span className={clsx('text-xs px-1.5 py-0.5 rounded border font-bold', map[level] ?? map.C)}>
      {level}
    </span>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function EquipmentHealth() {
  const { setActiveEquipment } = useUIStore();
  const navigate = useNavigate();

  const { data: summary, isLoading: loadingSummary } = useQuery({
    queryKey:  ['equipment', 'summary'],
    queryFn:   equipmentApi.summary,
    refetchInterval: 30_000,
  });

  const { data: equipment, isLoading: loadingEq, refetch } = useQuery({
    queryKey:  ['equipment', 'list'],
    queryFn:   () => equipmentApi.list(),
    refetchInterval: 30_000,
  });

  const handleRowClick = (eq: Equipment) => {
    setActiveEquipment(eq.equipment_id);
    navigate(`/copilot?eq=${eq.equipment_id}`);
  };

  if (loadingSummary || loadingEq) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <RefreshCw size={24} className="animate-spin mr-3" /> Loading plant data...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Equipment Health</h1>
          <p className="text-sm text-gray-400 mt-0.5">
            Real-time health overview · {equipment?.length ?? 0} assets monitored
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="flex items-center gap-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm text-gray-300 transition-colors"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <SummaryCard
            label="Healthy Assets"
            value={`${summary.healthy} / ${summary.total_equipment}`}
            color="blue"
            Icon={Activity}
          />
          <SummaryCard
            label="Active Anomalies"
            value={summary.warning + summary.urgent}
            sub={`${summary.urgent} urgent`}
            color="yellow"
            Icon={AlertTriangle}
          />
          <SummaryCard
            label="Critical Alerts"
            value={summary.critical_alerts}
            sub={`${summary.open_alerts} total open`}
            color="red"
            Icon={Zap}
          />
          <SummaryCard
            label="Avg RUL (Class A)"
            value={`${summary.avg_rul_critical_days} days`}
            color="orange"
            Icon={Clock}
          />
        </div>
      )}

      {/* Equipment table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Equipment Priority Queue</h2>
          <span className="text-xs text-gray-400">sorted by risk score ↓</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-400 border-b border-gray-800">
                <th className="text-left px-5 py-3 font-medium">Equipment</th>
                <th className="text-left px-4 py-3 font-medium">Area</th>
                <th className="text-left px-4 py-3 font-medium">Class</th>
                <th className="text-left px-4 py-3 font-medium">Status</th>
                <th className="text-left px-4 py-3 font-medium w-36">Priority Score</th>
                <th className="text-left px-4 py-3 font-medium">RUL (days)</th>
                <th className="text-left px-4 py-3 font-medium">Anomaly</th>
                <th className="text-left px-4 py-3 font-medium">Last Updated</th>
              </tr>
            </thead>
            <tbody>
              {equipment?.map((eq) => (
                <tr
                  key={eq.equipment_id}
                  onClick={() => handleRowClick(eq)}
                  className="border-b border-gray-800/50 hover:bg-gray-800/50 cursor-pointer transition-colors"
                >
                  <td className="px-5 py-3">
                    <div>
                      <p className="font-medium text-white text-xs">{eq.equipment_id}</p>
                      <p className="text-gray-400 text-xs truncate max-w-[200px]">{eq.name}</p>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400">{eq.plant_area_code}</td>
                  <td className="px-4 py-3"><CriticalityBadge level={eq.criticality} /></td>
                  <td className="px-4 py-3"><StatusBadge status={eq.status} /></td>
                  <td className="px-4 py-3 w-36"><PriorityBar score={eq.priority_score} /></td>
                  <td className="px-4 py-3">
                    <span className={clsx(
                      'text-xs font-mono font-bold',
                      (eq.rul_days ?? 999) < 7   ? 'text-red-400'    :
                      (eq.rul_days ?? 999) < 30  ? 'text-yellow-400' : 'text-green-400'
                    )}>
                      {eq.rul_days?.toFixed(0) ?? '—'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={clsx(
                      'text-xs font-mono',
                      (eq.anomaly_score ?? 0) >= 75 ? 'text-red-400'    :
                      (eq.anomaly_score ?? 0) >= 50 ? 'text-yellow-400' : 'text-gray-400'
                    )}>
                      {eq.anomaly_score?.toFixed(0) ?? '—'}/100
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {eq.last_health_update
                      ? new Date(eq.last_health_update).toLocaleTimeString()
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
