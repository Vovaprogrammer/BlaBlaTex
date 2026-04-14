import React, { useState } from 'react';
import { authAPI, setAuthToken } from '../services/api';

interface LoginProps {
    onSwitchToRegister: () => void;
    onLoginSuccess: () => void;
}

export const Login: React.FC<LoginProps> = ({ onSwitchToRegister, onLoginSuccess }) => {
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
        <div className="min-h-screen flex items-center justify-center bg-gray-100 dark:bg-gray-900">
            <div className="w-full max-w-md bg-white dark:bg-gray-800 rounded-xl shadow-lg p-8 border">
                
                <h1 className="text-2xl font-bold mb-6 text-center text-gray-900 dark:text-white">
                    Welcome
                </h1>

                {error && (
                    <div className="bg-red-100 text-red-700 p-3 rounded mb-4">
                        {error}
                    </div>
                )}

                <form onSubmit={handleSubmit}>
                    <input
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="Email"
                        className="w-full mb-3 px-3 py-2 border rounded dark:bg-gray-700 dark:text-white"
                    />

                    <input
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="Password"
                        className="w-full mb-4 px-3 py-2 border rounded dark:bg-gray-700 dark:text-white"
                    />

                    <button
                        type="submit"
                        disabled={loading}
                        className="w-full bg-blue-600 text-white py-2 rounded hover:bg-blue-700"
                    >
                        {loading ? 'Logging in...' : 'Login'}
                    </button>
                </form>

                <p className="text-center text-gray-600 dark:text-gray-300 mt-4">
                    Don't have an account?{' '}
                    <button onClick={onSwitchToRegister} className="text-blue-600 hover:underline">
                        Register
                    </button>
                </p>
            </div>
        </div>
    );
};