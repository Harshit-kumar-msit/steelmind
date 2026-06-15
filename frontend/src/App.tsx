// src/App.tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import { useAuthStore } from './store';
import Layout from './components/layout/Layout';
import EquipmentHealth from './pages/EquipmentHealth';
import AnomalyView      from './pages/AnomalyView';
import AlertsPage       from './pages/AlertsPage';
import MaintenancePlanner from './pages/MaintenancePlanner';
import CopilotChat      from './pages/CopilotChat';
import Reports          from './pages/Reports';
import LoginPage        from './pages/LoginPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime:  30_000,   // 30 seconds
      retry:      2,
      refetchInterval: 60_000,  // auto-refresh every 60s
    },
  },
});

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user);
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/*"
            element={
              <ProtectedRoute>
                <Layout>
                  <Routes>
                    <Route path="/"           element={<Navigate to="/health" replace />} />
                    <Route path="/health"     element={<EquipmentHealth />} />
                    <Route path="/anomaly"    element={<AnomalyView />} />
                    <Route path="/alerts"     element={<AlertsPage />} />
                    <Route path="/planner"    element={<MaintenancePlanner />} />
                    <Route path="/copilot"    element={<CopilotChat />} />
                    <Route path="/reports"    element={<Reports />} />
                  </Routes>
                </Layout>
              </ProtectedRoute>
            }
          />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" />
    </QueryClientProvider>
  );
}
