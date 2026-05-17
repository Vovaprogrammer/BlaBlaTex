import React, { useState } from 'react';
import { authAPI, setAuthToken } from '../services/api';
import { LogIn, Mail, Lock, Sparkles, Zap, Globe } from 'lucide-react';

interface LoginProps {
  onSwitchToRegister: () => void;
  onLoginSuccess: () => void;
}

const FEATURES = [
  { icon: Sparkles, text: '26 AI-функций для LaTeX' },
  { icon: Zap, text: 'Мгновенная компиляция PDF' },
  { icon: Globe, text: 'Доступ из любого браузера' },
];

export const Login: React.FC<LoginProps> = ({
  onSwitchToRegister,
  onLoginSuccess,
}) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const result = await authAPI.login(email, password);
      setAuthToken(result.access_token);
      onLoginSuccess();
    } catch (err: any) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex bg-gradient-to-br from-blue-600 via-indigo-700 to-purple-800">
      {/* Left side - Branding */}
      <div className="hidden lg:flex lg:w-6/12 flex-col justify-center pl-80 pr-0 text-white relative overflow-hidden">
        <div className="absolute -top-40 -left-40 w-80 h-80 bg-blue-400 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-pulse"></div>
        <div className="absolute -bottom-40 left-20 w-80 h-80 bg-purple-400 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-pulse" style={{ animationDelay: '2s' }}></div>

        <div className="relative z-10">
          <img
            src="/BlaBlaTex_icon.jpg"
            alt="BlaBlaTex"
            className="w-20 h-20 rounded-2xl shadow-lg object-cover mb-6"
          />
          <h1 className="text-4xl font-bold mb-3">BlaBlaTex</h1>
          <p className="text-blue-200 text-lg mb-10">AI-Powered LaTeX Editor</p>

          <div className="space-y-5">
            {FEATURES.map(({ icon: Icon, text }, i) => (
              <div key={i} className="flex items-center gap-4">
                <div className="w-10 h-10 bg-white/15 rounded-xl flex items-center justify-center flex-shrink-0">
                  <Icon className="w-5 h-5 text-blue-200" />
                </div>
                <span className="text-white/90 text-base">{text}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right side - Form */}
      <div className="w-full lg:w-6/12 flex items-center justify-center pr-60 pl-0">
        <div className="w-full max-w-md">
          {/* Mobile logo */}
          <div className="lg:hidden text-center mb-6">
            <img src="/BlaBlaTex_icon.jpg" alt="BlaBlaTex" className="w-14 h-14 rounded-xl shadow-lg object-cover mx-auto mb-3" />
            <h2 className="text-2xl font-bold text-white">BlaBlaTex</h2>
          </div>

          <div className="bg-white/95 backdrop-blur-sm rounded-2xl shadow-2xl p-8 border border-white/20">
            <div className="flex items-center gap-3 mb-6">
              <div className="w-10 h-10 bg-blue-100 rounded-xl flex items-center justify-center">
                <LogIn className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <h2 className="text-xl font-semibold text-gray-800">Welcome back</h2>
                <p className="text-sm text-gray-500">Sign in to continue</p>
              </div>
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl mb-4 text-sm flex items-center gap-2">
                <span>⚠️</span> {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Email</label>
                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                    className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-gray-800 placeholder-gray-400 transition-all"
                    placeholder="you@example.com" required
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">Password</label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                  <input
                    type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                    className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-gray-800 placeholder-gray-400 transition-all"
                    placeholder="••••••••" required
                  />
                </div>
              </div>
              <button
                type="submit" disabled={loading}
                className="w-full bg-gradient-to-r from-blue-600 to-indigo-600 text-white py-2.5 rounded-xl font-medium hover:from-blue-700 hover:to-indigo-700 transition-all shadow-lg hover:shadow-xl disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {loading ? <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <LogIn className="w-4 h-4" />}
                {loading ? 'Logging in...' : 'Login'}
              </button>
            </form>
            <p className="text-center text-gray-500 mt-6 text-sm">
              Don't have an account?{' '}
              <button onClick={onSwitchToRegister} className="text-blue-600 hover:text-blue-700 font-medium hover:underline">Create one</button>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};