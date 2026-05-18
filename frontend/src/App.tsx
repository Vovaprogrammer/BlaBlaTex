import React, { useEffect, useState } from 'react';
import { Login } from './components/Login';
import { Register } from './components/Register';
import { DocumentSidebar } from './components/DocumentSidebar';
import { LaTeXEditor } from './components/LaTeXEditor';
import { PDFViewer } from './components/PDFViewer';
import { AIAssistant } from './components/AIAssistant';
import { TemplatesPanel } from './components/TemplatesPanel';
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
    const [showTemplates, setShowTemplates] = useState(false);

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
            handleReplaceCode,
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
        return (
            <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-600 via-indigo-700 to-purple-800">
                <div className="text-center">
                    <img
                        src="/BlaBlaTex_icon.jpg"
                        alt="BlaBlaTex"
                        className="w-20 h-20 rounded-2xl shadow-lg object-cover mx-auto mb-6 animate-pulse"
                    />
                    <h1 className="text-3xl font-bold text-white mb-2">BlaBlaTex</h1>
                    <div className="flex items-center justify-center gap-2 text-blue-200">
                        <div className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                        <div className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                        <div className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                    </div>
                </div>
            </div>
        );
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
        <div className="h-screen bg-gradient-to-br from-slate-300 via-blue-300 to-indigo-300 dark:bg-gradient-to-br dark:from-slate-950 dark:via-indigo-950 dark:to-blue-950 flex overflow-hidden">
            <DocumentSidebar
                currentDocument={currentDocument}
                onSelectDocument={handleDocumentSelect}
                onNewDocument={handleNewDocument}
            />
            <div className="flex flex-col flex-1">
                {/* Header */}
                <header className="bg-gradient-to-r from-slate-300 via-blue-300 to-indigo-300 dark:bg-gradient-to-r dark:from-slate-950 dark:via-indigo-950 dark:to-blue-950 border-b border-gray-200 dark:border-white/10 px-6 py-3 flex items-center justify-between flex-shrink-0 shadow-sm dark:shadow-lg">
                    {/* Левая часть — брендинг и заголовок */}
                    <div className="flex items-center gap-4">
                        <img
                            src="/BlaBlaTex_icon.jpg"
                            alt="BlaBlaTex"
                            className="w-8 h-8 rounded-lg shadow-md object-cover"
                        />
                        <h1 className="text-xl font-bold text-white">BlaBlaTex</h1>
                        <div className="h-6 w-px bg-white/20"></div>
                        <input
                            type="text"
                            value={title}
                            onChange={(e) => {
                                setTitle(e.target.value);
                                setHasUnsavedChanges(true);
                            }}
                            className="text-lg font-medium text-white/90 bg-white/10 border border-white/20 rounded-lg px-3 py-1 outline-none focus:bg-white/20 focus:border-white/40 placeholder-white/40 transition-all min-w-[200px]"
                            placeholder="Untitled document"
                        />
                        {hasUnsavedChanges && (
                            <span className="text-xs text-yellow-300 font-medium bg-yellow-500/20 px-2 py-0.5 rounded-full">
                                Unsaved
                            </span>
                        )}
                    </div>

                    {/* Правая часть — действия и аккаунт */}
                    <div className="flex items-center gap-1">
                        {/* Группа действий */}
                        <div className="flex items-center gap-1 bg-white/10 rounded-lg p-1">
                            <button
                                onClick={() => setShowTemplates(!showTemplates)}
                                className="px-3 py-1.5 text-sm font-medium text-white/90 hover:text-white hover:bg-white/15 rounded-md transition-all flex items-center gap-1.5"
                            >
                                📄 Templates
                            </button>
                            <button
                                onClick={saveDocument}
                                className="px-3 py-1.5 text-sm font-medium text-white/90 hover:text-white hover:bg-white/15 rounded-md transition-all flex items-center gap-1.5"
                            >
                                💾 Save
                            </button>
                        </div>

                        {/* Разделитель */}
                        <div className="h-8 w-px bg-white/20 mx-2"></div>

                        {/* Группа аккаунта */}
                        <div className="flex items-center gap-1 bg-white/10 rounded-lg p-1">
                            <button
                                onClick={toggleTheme}
                                className="px-2.5 py-1.5 text-sm font-medium text-white/90 hover:text-white hover:bg-white/15 rounded-md transition-all"
                                title="Toggle theme"
                            >
                                {theme === "light" ? "🌙" : "☀️"}
                            </button>
                            <UserMenu />
                        </div>
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
            {showTemplates && (
                <TemplatesPanel
                    onInsertCode={handleReplaceCode}
                    onClose={() => setShowTemplates(false)}
                />
            )}
        </div>
    );
}

export default App;