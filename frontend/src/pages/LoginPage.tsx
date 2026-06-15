// src/pages/LoginPage.tsx
import { useState, FormEvent } from 'react';
import { useNavigate }         from 'react-router-dom';
import { Activity, AlertTriangle } from 'lucide-react';
import { authApi }             from '../api/client';
import { useAuthStore }        from '../store';

export default function LoginPage() {
  const navigate  = useNavigate();
  const { setUser } = useAuthStore();
  const [email, setEmail]       = useState('engineer@steelmind.demo');
  const [password, setPassword] = useState('demo1234');
  const [error, setError]       = useState('');
  const [loading, setLoading]   = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const data = await authApi.login(email, password);
      setUser({
        user_id:      data.user_id,
        full_name:    data.full_name,
        role:         data.role,
        access_token: data.access_token,
      });
      navigate('/health');
    } catch {
      setError('Invalid credentials. Use the demo credentials below.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-6">
        {/* Logo */}
        <div className="text-center">
          <div className="w-14 h-14 rounded-2xl bg-blue-600 flex items-center justify-center mx-auto mb-4">
            <Activity size={28} className="text-white" />
          </div>
          <h1 className="text-2xl font-bold text-white">SteelMind</h1>
          <p className="text-sm text-gray-400 mt-1">Intelligent Maintenance Wizard</p>
        </div>

        {/* Form */}
        <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 space-y-4">
          <h2 className="text-base font-semibold text-white">Sign in</h2>

          {error && (
            <div className="flex items-center gap-2 text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
              <AlertTriangle size={14} />
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label className="text-xs text-gray-400 block mb-1">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2.5 text-sm text-white focus:outline-none focus:border-blue-500 transition-colors"
                required
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 block mb-1">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2.5 text-sm text-white focus:outline-none focus:border-blue-500 transition-colors"
                required
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-60 text-white text-sm font-medium py-2.5 rounded-lg transition-colors"
            >
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>

        {/* Demo credentials */}
        <div className="bg-blue-500/5 border border-blue-500/20 rounded-xl p-4 text-xs text-blue-300 space-y-1">
          <p className="font-semibold text-blue-400 mb-2">Demo Credentials</p>
          <p>Engineer: <span className="font-mono">engineer@steelmind.demo</span></p>
          <p>Manager:  <span className="font-mono">manager@steelmind.demo</span></p>
          <p>Password: <span className="font-mono">demo1234</span></p>
        </div>
      </div>
    </div>
  );
}
