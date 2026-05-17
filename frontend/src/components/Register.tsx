import React, { useState } from 'react';
import { authAPI, setAuthToken } from '../services/api';
import { UserPlus, Mail, User, Lock, ShieldCheck, Wand2, FileText, Book } from 'lucide-react';

interface RegisterProps {
    onSwitchToLogin: () => void;
    onRegisterSuccess: () => void;
}

const FEATURES = [
  { icon: Wand2, text: 'Генерация полных документов' },
  { icon: FileText, text: 'Таблицы, графики, диаграммы' },
  { icon: Book, text: 'Форматирование библиографии' },
];

export const Register: React.FC<RegisterProps> = ({ onSwitchToLogin, onRegisterSuccess }) => {
    const [email, setEmail] = useState('');
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [confirmPassword, setConfirmPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        if (password !== confirmPassword) { setError('Passwords do not match'); return; }
        if (password.length < 6) { setError('Password must be at least 6 characters'); return; }
        setLoading(true);
        try {
            const result = await authAPI.register(email, username, password);
            setAuthToken(result.access_token);
            onRegisterSuccess();
        } catch (err: any) {
            setError(err.message || 'Registration failed');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex bg-gradient-to-br from-emerald-600 via-teal-700 to-cyan-800">
            {/* Left side - Branding */}
            <div className="hidden lg:flex lg:w-6/12 flex-col justify-center pl-80 pr-0 text-white relative overflow-hidden">
                <div className="absolute -top-40 -left-40 w-80 h-80 bg-emerald-400 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-pulse"></div>
                <div className="absolute -bottom-40 left-20 w-80 h-80 bg-cyan-400 rounded-full mix-blend-multiply filter blur-3xl opacity-20 animate-pulse" style={{ animationDelay: '2s' }}></div>

                <div className="relative z-10">
                    <img src="/BlaBlaTex_icon.jpg" alt="BlaBlaTex" className="w-20 h-20 rounded-2xl shadow-lg object-cover mb-6" />
                    <h1 className="text-4xl font-bold mb-3">BlaBlaTex</h1>
                    <p className="text-emerald-200 text-lg mb-10">Начните создавать документы</p>

                    <div className="space-y-5">
                        {FEATURES.map(({ icon: Icon, text }, i) => (
                            <div key={i} className="flex items-center gap-4">
                                <div className="w-10 h-10 bg-white/15 rounded-xl flex items-center justify-center flex-shrink-0">
                                    <Icon className="w-5 h-5 text-emerald-200" />
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
                    <div className="lg:hidden text-center mb-6">
                        <img src="/BlaBlaTex_icon.jpg" alt="BlaBlaTex" className="w-14 h-14 rounded-xl shadow-lg object-cover mx-auto mb-3" />
                        <h2 className="text-2xl font-bold text-white">BlaBlaTex</h2>
                    </div>

                    <div className="bg-white/95 backdrop-blur-sm rounded-2xl shadow-2xl p-8 border border-white/20">
                        <div className="flex items-center gap-3 mb-6">
                            <div className="w-10 h-10 bg-emerald-100 rounded-xl flex items-center justify-center">
                                <UserPlus className="w-5 h-5 text-emerald-600" />
                            </div>
                            <div>
                                <h2 className="text-xl font-semibold text-gray-800">Create account</h2>
                                <p className="text-sm text-gray-500">Start your journey</p>
                            </div>
                        </div>

                        {error && (
                            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-xl mb-4 text-sm flex items-center gap-2">
                                <span>⚠️</span> {error}
                            </div>
                        )}

                        <form onSubmit={handleSubmit} className="space-y-3.5">
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                                <div className="relative">
                                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                                    <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
                                        className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-gray-800 placeholder-gray-400 transition-all"
                                        placeholder="you@example.com" required />
                                </div>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                                <div className="relative">
                                    <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                                    <input type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                                        className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-gray-800 placeholder-gray-400 transition-all"
                                        placeholder="your_username" required minLength={3} />
                                </div>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                                <div className="relative">
                                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                                    <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                                        className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-gray-800 placeholder-gray-400 transition-all"
                                        placeholder="••••••••" required minLength={6} />
                                </div>
                            </div>
                            <div>
                                <label className="block text-sm font-medium text-gray-700 mb-1">Confirm Password</label>
                                <div className="relative">
                                    <ShieldCheck className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                                    <input type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)}
                                        className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent text-gray-800 placeholder-gray-400 transition-all"
                                        placeholder="••••••••" required />
                                </div>
                            </div>
                            <button
                                type="submit" disabled={loading}
                                className="w-full bg-gradient-to-r from-emerald-600 to-teal-600 text-white py-2.5 rounded-xl font-medium hover:from-emerald-700 hover:to-teal-700 transition-all shadow-lg hover:shadow-xl disabled:opacity-50 flex items-center justify-center gap-2 mt-1"
                            >
                                {loading ? <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <UserPlus className="w-4 h-4" />}
                                {loading ? 'Creating account...' : 'Register'}
                            </button>
                        </form>
                        <p className="text-center text-gray-500 mt-5 text-sm">
                            Already have an account?{' '}
                            <button onClick={onSwitchToLogin} className="text-emerald-600 hover:text-emerald-700 font-medium hover:underline">Sign in</button>
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
};