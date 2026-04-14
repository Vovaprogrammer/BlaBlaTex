import React from 'react';

interface LoginProps {
  backendUrl: string;
}

export const Login: React.FC<LoginProps> = ({ backendUrl }) => {
  const handleSignIn = (provider: string) => {
    window.location.href = `${backendUrl}/auth/signin/${provider}`;
  };

  return (
    <div className="h-screen flex items-center justify-center bg-gray-100 dark:bg-gray-900">
      <div className="w-full max-w-md bg-white dark:bg-gray-800 rounded-xl shadow-lg p-8 text-center border">
        <h1 className="text-2xl font-bold mb-6">Welcome to AI LaTeX Editor</h1>
        <p className="mb-4">Please sign in to continue</p>
        <div className="flex flex-col gap-3">
  
          <button
            onClick={() => handleSignIn('google')}
            className="px-6 py-3 bg-red-600 text-white rounded hover:bg-red-700 transition-colors"
          >
            Sign in with Google
          </button>
         
        </div>
      </div>
    </div>
  );
};
