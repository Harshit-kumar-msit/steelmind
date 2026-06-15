// src/components/layout/Layout.tsx
import { NavLink, useLocation }  from 'react-router-dom';
import { Activity, AlertTriangle, Bell, Calendar, MessageSquare, BarChart3, LogOut, Menu, X } from 'lucide-react';
import { useAuthStore, useUIStore, useAlertCountStore } from '../../store';
import clsx from 'clsx';
import { useQuery } from '@tanstack/react-query';
import { alertsApi } from '../../api/client';
import { useEffect } from 'react';

const NAV_ITEMS = [
  { path: '/health',   label: 'Equipment Health', Icon: Activity },
  { path: '/anomaly',  label: 'Anomaly View',     Icon: Activity },
  { path: '/alerts',   label: 'Alerts',           Icon: Bell, badge: true },
  { path: '/planner',  label: 'Maintenance Plan', Icon: Calendar },
  { path: '/copilot',  label: 'AI Copilot',       Icon: MessageSquare },
  { path: '/reports',  label: 'Reports',           Icon: BarChart3 },
];

export default function Layout({ children }: { children: React.ReactNode }) {
  const { user, logout }   = useAuthStore();
  const { sidebarOpen, setSidebarOpen } = useUIStore();
  const { criticalCount, setCount } = useAlertCountStore();

  // Poll alert counts every 30s
  const { data: alerts } = useQuery({
    queryKey: ['alerts', 'open'],
    queryFn:  () => alertsApi.list({ status: 'open' }),
    refetchInterval: 30_000,
  });

  useEffect(() => {
    if (alerts) {
      const critical = alerts.filter((a) => a.severity === 'critical').length;
      setCount(alerts.length, critical);
    }
  }, [alerts, setCount]);

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden">
      {/* ── Sidebar ── */}
      <aside
        className={clsx(
          'flex flex-col bg-gray-900 border-r border-gray-800 transition-all duration-300 flex-shrink-0',
          sidebarOpen ? 'w-60' : 'w-16'
        )}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 py-5 border-b border-gray-800">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center flex-shrink-0">
            <Activity size={16} className="text-white" />
          </div>
          {sidebarOpen && (
            <div>
              <span className="font-bold text-white text-sm">SteelMind</span>
              <p className="text-xs text-gray-400">Maintenance AI</p>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-4 space-y-1">
          {NAV_ITEMS.map(({ path, label, Icon, badge }) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                    : 'text-gray-400 hover:bg-gray-800 hover:text-white'
                )
              }
            >
              <div className="relative flex-shrink-0">
                <Icon size={18} />
                {badge && criticalCount > 0 && (
                  <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 text-white text-[10px] rounded-full flex items-center justify-center font-bold">
                    {criticalCount > 9 ? '9+' : criticalCount}
                  </span>
                )}
              </div>
              {sidebarOpen && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* User + logout */}
        <div className="px-3 py-4 border-t border-gray-800">
          {sidebarOpen && user && (
            <div className="mb-3 px-1">
              <p className="text-xs font-medium text-white truncate">{user.full_name}</p>
              <p className="text-xs text-gray-400 capitalize">{user.role}</p>
            </div>
          )}
          <button
            onClick={logout}
            className={clsx(
              'flex items-center gap-3 w-full px-3 py-2 rounded-lg text-sm text-gray-400 hover:text-red-400 hover:bg-gray-800 transition-colors',
            )}
          >
            <LogOut size={16} className="flex-shrink-0" />
            {sidebarOpen && 'Logout'}
          </button>
        </div>
      </aside>

      {/* ── Main content ── */}
      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Top bar */}
        <header className="h-14 bg-gray-900 border-b border-gray-800 flex items-center justify-between px-4 flex-shrink-0">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-2 rounded-lg hover:bg-gray-800 text-gray-400 hover:text-white transition-colors"
          >
            {sidebarOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
          <div className="flex items-center gap-4">
            <span className="text-xs text-gray-400">Bhilai Steel Plant · Zone 3</span>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              <span className="text-xs text-green-400">LIVE</span>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
