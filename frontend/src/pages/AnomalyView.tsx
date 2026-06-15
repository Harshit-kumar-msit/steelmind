// src/pages/AnomalyView.tsx
// Purpose: Per-equipment anomaly deep-dive with sensor trend charts,
//          anomaly score timeline, and per-sensor z-score breakdown.
// Charts: Recharts LineChart for time-series, RadialBar for score gauge.

import { useState } from 'react';
import { useQuery }  from '@tanstack/react-query';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, AreaChart, Area,
} from 'recharts';
import { RefreshCw, Activity, Thermometer, Gauge, Zap } from 'lucide-react';
import clsx from 'clsx';
import { sensorsApi, equipmentApi, anomalyApi } from '../api/client';
import type { Equipment } from '../types';
import { format } from 'date-fns';

// ── Sensor icon map ───────────────────────────────────────────────────────────
const SENSOR_META: Record<string, { label: string; unit: string; Icon: React.ElementType; color: string; warningLine?: number; criticalLine?: number }> = {
  vibration_rms_mm_s: { label: 'Vibration RMS',     unit: 'mm/s', Icon: Activity,    color: '#60a5fa', warningLine: 4.5,  criticalLine: 7.1 },
  bearing_temp_c:     { label: 'Bearing Temp',       unit: '°C',   Icon: Thermometer, color: '#f97316', warningLine: 80,   criticalLine: 95 },
  lube_pressure_bar:  { label: 'Lube Oil Pressure',  unit: 'bar',  Icon: Gauge,       color: '#34d399', warningLine: 3.5,  criticalLine: 3.0 },
  motor_current_a:    { label: 'Motor Current',      unit: 'A',    Icon: Zap,         color: '#a78bfa' },
  outlet_temp_c:      { label: 'Outlet Temperature', unit: '°C',   Icon: Thermometer, color: '#fb923c' },
  speed_rpm:          { label: 'Shaft Speed',        unit: 'rpm',  Icon: Activity,    color: '#94a3b8' },
};

// ── Sensor Chart ─────────────────────────────────────────────────────────────

function SensorChart({ equipmentId, field }: { equipmentId: string; field: string }) {
  const meta   = SENSOR_META[field] ?? { label: field, unit: '', color: '#60a5fa', Icon: Activity };
  const { data, isLoading } = useQuery({
    queryKey: ['sensor', equipmentId, field, 24],
    queryFn:  () => sensorsApi.history(equipmentId, field, 24),
    refetchInterval: 60_000,
  });

  const chartData = (data ?? []).map((d) => ({
    time:  format(new Date(d.time), 'HH:mm'),
    value: d.value,
  }));

  const values = chartData.map((d) => d.value ?? 0);
  const maxVal = values.length ? Math.max(...values) * 1.15 : 10;
  const minVal = values.length ? Math.min(...values) * 0.85 : 0;

  if (isLoading) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 h-48 flex items-center justify-center">
        <RefreshCw size={18} className="animate-spin text-gray-600" />
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <meta.Icon size={14} style={{ color: meta.color }} />
          <span className="text-xs font-medium text-gray-300">{meta.label}</span>
        </div>
        <span className="text-xs text-gray-500">{meta.unit} · last 24h</span>
      </div>
      <ResponsiveContainer width="100%" height={120}>
        <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
          <defs>
            <linearGradient id={`grad-${field}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%"  stopColor={meta.color} stopOpacity={0.25} />
              <stop offset="95%" stopColor={meta.color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis dataKey="time" tick={{ fontSize: 9, fill: '#6b7280' }} interval="preserveStartEnd" />
          <YAxis domain={[minVal, maxVal]} tick={{ fontSize: 9, fill: '#6b7280' }} />
          <Tooltip
            contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: '8px', fontSize: 11 }}
            labelStyle={{ color: '#9ca3af' }}
          />
          {meta.warningLine  && <ReferenceLine y={meta.warningLine}  stroke="#f59e0b" strokeDasharray="4 4" strokeWidth={1} />}
          {meta.criticalLine && <ReferenceLine y={meta.criticalLine} stroke="#ef4444" strokeDasharray="4 4" strokeWidth={1} />}
          <Area
            type="monotone" dataKey="value" stroke={meta.color} strokeWidth={1.5}
            fill={`url(#grad-${field})`} dot={false} isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Anomaly Score Gauge ───────────────────────────────────────────────────────

function AnomalyGauge({ score, severity }: { score: number; severity: string }) {
  const color = severity === 'critical' ? '#ef4444' : severity === 'warning' ? '#f59e0b' : '#34d399';
  const rotation = -135 + (score / 100) * 270;

  return (
    <div className="flex flex-col items-center justify-center p-6 bg-gray-900 border border-gray-800 rounded-xl">
      <div className="relative w-32 h-32">
        <svg viewBox="0 0 120 120" className="w-full h-full">
          {/* Background arc */}
          <path
            d="M 15 95 A 55 55 0 1 1 105 95"
            fill="none" stroke="#1f2937" strokeWidth="12" strokeLinecap="round"
          />
          {/* Score arc */}
          <path
            d="M 15 95 A 55 55 0 1 1 105 95"
            fill="none" stroke={color} strokeWidth="12" strokeLinecap="round"
            strokeDasharray={`${(score / 100) * 259} 259`}
            opacity={0.9}
          />
          {/* Needle center */}
          <circle cx="60" cy="60" r="5" fill={color} />
          {/* Score text */}
          <text x="60" y="78" textAnchor="middle" fill="white" fontSize="22" fontWeight="bold">
            {score.toFixed(0)}
          </text>
          <text x="60" y="92" textAnchor="middle" fill="#6b7280" fontSize="9">
            / 100
          </text>
        </svg>
      </div>
      <div className="mt-2 text-center">
        <p className="text-xs font-medium text-gray-400">Anomaly Score</p>
        <span
          className={clsx(
            'text-xs px-2 py-0.5 rounded font-medium uppercase',
            severity === 'critical' ? 'text-red-400 bg-red-500/10' :
            severity === 'warning'  ? 'text-yellow-400 bg-yellow-500/10' :
                                      'text-green-400 bg-green-500/10',
          )}
        >
          {severity}
        </span>
      </div>
    </div>
  );
}

// ── Contribution Bar Chart ────────────────────────────────────────────────────

function ContributionBreakdown({ contributions }: { contributions: Record<string, number> }) {
  const entries = Object.entries(contributions).sort((a, b) => b[1] - a[1]);
  const max     = Math.max(...entries.map(([, v]) => v), 1);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <p className="text-xs font-medium text-gray-400 mb-3 uppercase tracking-wide">Anomaly Contributions</p>
      <div className="space-y-2.5">
        {entries.map(([sensor, val]) => {
          const meta = SENSOR_META[sensor];
          const pct  = (val / max) * 100;
          return (
            <div key={sensor}>
              <div className="flex justify-between mb-1">
                <span className="text-xs text-gray-300">{meta?.label ?? sensor}</span>
                <span className="text-xs font-mono text-gray-400">{val.toFixed(2)}</span>
              </div>
              <div className="h-1.5 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${pct}%`, background: meta?.color ?? '#60a5fa' }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Anomaly Timeline ──────────────────────────────────────────────────────────

function AnomalyTimeline({ equipmentId }: { equipmentId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['anomaly-chart', equipmentId],
    queryFn:  () => sensorsApi.anomalyChart(equipmentId, 72),
    refetchInterval: 60_000,
  });

  const chartData = (data ?? []).map((d) => ({
    time:  format(new Date(d.time), 'dd/MM HH:mm'),
    score: d.value ?? 0,
  }));

  if (isLoading) return <div className="h-32 flex items-center justify-center text-gray-600"><RefreshCw size={16} className="animate-spin" /></div>;

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <p className="text-xs font-medium text-gray-400 mb-3 uppercase tracking-wide">Anomaly Score — 72h Trend</p>
      <ResponsiveContainer width="100%" height={100}>
        <AreaChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
          <defs>
            <linearGradient id="anomaly-grad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis dataKey="time" tick={{ fontSize: 8, fill: '#4b5563' }} interval="preserveStartEnd" />
          <YAxis domain={[0, 100]} tick={{ fontSize: 8, fill: '#4b5563' }} />
          <Tooltip contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: '8px', fontSize: 11 }} />
          <ReferenceLine y={75} stroke="#ef4444" strokeDasharray="4 4" strokeWidth={1} label={{ value: 'Critical', fill: '#ef4444', fontSize: 9 }} />
          <ReferenceLine y={50} stroke="#f59e0b" strokeDasharray="4 4" strokeWidth={1} label={{ value: 'Warning', fill: '#f59e0b', fontSize: 9 }} />
          <Area type="monotone" dataKey="score" stroke="#ef4444" strokeWidth={1.5} fill="url(#anomaly-grad)" dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function AnomalyView() {
  const [selectedEq, setSelectedEq] = useState('EQ-BF-001');

  const { data: equipment } = useQuery({
    queryKey: ['equipment', 'list'],
    queryFn:  () => equipmentApi.list(),
  });

  const { data: anomaly, isLoading: anomalyLoading, refetch } = useQuery({
    queryKey:        ['anomaly-score', selectedEq],
    queryFn:         () => anomalyApi.score(selectedEq),
    refetchInterval: 30_000,
    enabled:         !!selectedEq,
  });

  const anomalousEquipment = (equipment ?? []).filter(
    (e) => (e.anomaly_score ?? 0) >= 50
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Anomaly Detection</h1>
          <p className="text-sm text-gray-400 mt-0.5">
            Real-time Isolation Forest · {anomalousEquipment.length} equipment showing anomalies
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="flex items-center gap-2 px-3 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg text-sm text-gray-300 transition-colors"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {/* Equipment selector */}
      <div className="flex gap-2 flex-wrap">
        {(equipment ?? []).map((eq) => (
          <button
            key={eq.equipment_id}
            onClick={() => setSelectedEq(eq.equipment_id)}
            className={clsx(
              'text-xs px-3 py-1.5 rounded-lg border font-medium transition-colors',
              selectedEq === eq.equipment_id
                ? 'bg-blue-600 border-blue-500 text-white'
                : (eq.anomaly_score ?? 0) >= 75
                ? 'border-red-500/40 text-red-400 bg-red-500/5 hover:bg-red-500/10'
                : (eq.anomaly_score ?? 0) >= 50
                ? 'border-yellow-500/40 text-yellow-400 bg-yellow-500/5 hover:bg-yellow-500/10'
                : 'border-gray-700 text-gray-400 bg-gray-800 hover:bg-gray-700',
            )}
          >
            {eq.equipment_id}
            {(eq.anomaly_score ?? 0) >= 50 && (
              <span className="ml-1.5 text-[10px] opacity-80">
                {eq.anomaly_score?.toFixed(0)}
              </span>
            )}
          </button>
        ))}
      </div>

      {anomaly && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Left: Gauge + contributions */}
          <div className="space-y-4">
            <AnomalyGauge score={anomaly.anomaly_score} severity={anomaly.severity} />
            {Object.keys(anomaly.contributions).length > 0 && (
              <ContributionBreakdown contributions={anomaly.contributions} />
            )}

            {/* Z-scores */}
            {Object.keys(anomaly.z_scores).length > 0 && (
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
                <p className="text-xs font-medium text-gray-400 mb-3 uppercase tracking-wide">Z-Scores vs Baseline</p>
                <div className="space-y-2">
                  {Object.entries(anomaly.z_scores).map(([sensor, z]) => (
                    <div key={sensor} className="flex justify-between items-center">
                      <span className="text-xs text-gray-300">{SENSOR_META[sensor]?.label ?? sensor}</span>
                      <span className={clsx(
                        'text-xs font-mono font-bold px-2 py-0.5 rounded',
                        z > 3 ? 'text-red-400 bg-red-500/10' :
                        z > 2 ? 'text-yellow-400 bg-yellow-500/10' :
                                'text-gray-400 bg-gray-800',
                      )}>
                        σ {z.toFixed(2)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Right: Sensor charts */}
          <div className="lg:col-span-2 space-y-4">
            <AnomalyTimeline equipmentId={selectedEq} />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {Object.keys(SENSOR_META).slice(0, 4).map((field) => (
                <SensorChart key={field} equipmentId={selectedEq} field={field} />
              ))}
            </div>
          </div>
        </div>
      )}

      {anomalyLoading && (
        <div className="flex items-center justify-center py-16 text-gray-400">
          <RefreshCw size={20} className="animate-spin mr-3" /> Running anomaly detection…
        </div>
      )}
    </div>
  );
}
