import React, { useEffect, useState } from 'react';
import { Login } from './components/Login';
import { Register } from './components/Register';
import { DocumentSidebar } from './components/DocumentSidebar';
import { LaTeXEditor } from './components/LaTeXEditor';
import { PDFViewer } from './components/PDFViewer';
import { AIAssistant } from './components/AIAssistant';
import { ResizablePanes } from './components/ResizablePanes';
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts';
import { useDocumentHandlers } from './hooks/useDocumentHandlers';
import { DEFAULT_APP_TEMPLATE } from './constants/newDocumentTemplate';
import { UserMenu } from './components/UserMenu';
import { getAuthToken, setAuthToken, authAPI } from './services/api';

function App() {
    const [theme, setTheme] = useState<"light" | "dark">("light");
    const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
    const [showRegister, setShowRegister] = useState(false);

// тема
    useEffect(() => {
        document.documentElement.classList.toggle("dark", theme === "dark");
    }, [theme]);

    const toggleTheme = () => {
        setTheme(prev => (prev === "light" ? "dark" : "light"));
    };

    // Проверка токена при загрузке
    useEffect(() => {
        const token = getAuthToken();
        console.log('Checking token:', token ? 'present' : 'not present');
        
        if (token) {
            setAuthToken(token);
            authAPI.getCurrentUser()
                .then((user) => {
                    console.log('User authenticated:', user);
                    setIsAuthenticated(true);
                })
                .catch((err) => {
                    console.error('Auth error:', err);
                    setAuthToken(null);
                    setIsAuthenticated(false);
                });
        } else {
            console.log('No token, not authenticated');
            setIsAuthenticated(false);
        }
    }, []);

    const {
        state: { currentDocument, content, title, compileResult, compiling, fixingErrors, hasUnsavedChanges },
        setters: { setTitle, setContent, setCurrentDocument, setCompileResult, setHasUnsavedChanges },
        handlers: {
            handleDocumentSelect,
            handleNewDocument,
            saveDocument,
            handleContentChange,
            handleCompile,
            handleFixErrors,
            handleInsertCode,
        },
    } = useDocumentHandlers();

    useEffect(() => {
        if (!currentDocument && !content) {
            setContent(DEFAULT_APP_TEMPLATE);
        }
    }, [currentDocument, content, setContent]);

    useKeyboardShortcuts({
        currentDocument,
        title,
        content,
        setTitle,
        setContent,
        setCurrentDocument,
        setCompileResult,
        setHasUnsavedChanges,
        saveDocument,
        handleCompile,
        handleNewDocument,
    });

    // Пока проверяем авторизацию
    if (isAuthenticated === null) {
        return <div className="min-h-screen flex items-center justify-center">Loading...</div>;
    }

    // Если не авторизован — показываем логин/регистрацию
    
    if (!isAuthenticated) {
  if (showRegister) {
    return (
      <Register
        onSwitchToLogin={() => setShowRegister(false)}
        onRegisterSuccess={() => {
          console.log('Register success');
          setIsAuthenticated(true);
        }}
      />
    );
  }

  return (
    <Login
      onSwitchToRegister={() => setShowRegister(true)}
      onLoginSuccess={() => {
        console.log('Login success');
        setIsAuthenticated(true);
      }}
    />
  );
}
    

    // Авторизован — показываем полноценный редактор
    console.log('Rendering full editor');
    return (
        <div className="h-screen bg-gray-100 dark:bg-gray-900 flex overflow-hidden">
            <DocumentSidebar
                currentDocument={currentDocument}
                onSelectDocument={handleDocumentSelect}
                onNewDocument={handleNewDocument}
            />
            <div className="flex flex-col flex-1">
                <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4 flex items-center justify-between flex-shrink-0">
                    <div className="flex items-center gap-4">
                        <h1 className="text-xl font-semibold text-gray-900 dark:text-white">BlaBlaTex</h1>
                        <input
                            type="text"
                            value={title}
                            onChange={(e) => {
                                setTitle(e.target.value);
                                setHasUnsavedChanges(true);
                            }}
                            className="text-lg font-medium text-gray-700 dark:text-gray-300 bg-transparent border-none outline-none hover:bg-gray-50 dark:hover:bg-gray-700 focus:bg-white dark:focus:bg-gray-800 focus:ring-2 focus:ring-blue-500 rounded px-2 py-1 transition-colors"
                            placeholder="Untitled document"
                        />
                        {hasUnsavedChanges && (
                            <span className="text-sm text-orange-600 font-medium">
                                Unsaved changes
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-3">
                        <button
                            onClick={saveDocument}
                            className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900 hover:bg-gray-100 rounded-md transition-colors"
                        >
                            Save
                        </button>
                        <button
                            onClick={() => {
                                authAPI.logout();
                                setIsAuthenticated(false);
                            }}
                            className="px-4 py-2 text-sm font-medium text-red-600 hover:text-red-700 hover:bg-red-50 rounded-md transition-colors"
                        >
                            Logout
                        </button>
                        <button
                            onClick={toggleTheme}
                            className="px-3 py-1 text-sm border rounded"
                        >
                            {theme === "light" ? "🌙" : "☀️"}
                        </button>
                    </div>
                </header>

                <div className="overflow-hidden flex-1">
                    <ResizablePanes
                        defaultLeftWidth={45}
                        left={
                            <LaTeXEditor
                                content={content}
                                onChange={handleContentChange}
                                onCompile={handleCompile}
                                compiling={compiling}
                                hasErrors={!!(compileResult?.error_log && compileResult.error_log.trim())}
                            />
                        }
                        right={
                            <ResizablePanes
                                defaultLeftWidth={60}
                                left={
                                    <PDFViewer
                                        pdfBase64={compileResult?.pdf_base64 || null}
                                        errorLog={compileResult?.error_log || ''}
                                        loading={compiling}
                                        onFixErrors={handleFixErrors}
                                        fixingErrors={fixingErrors}
                                    />
                                }
                                right={<AIAssistant onInsertCode={handleInsertCode} />}
                            />
                        }
                    />
                </div>
            </div>
        </div>
    );
}

export default App;