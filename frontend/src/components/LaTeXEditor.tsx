import React, { useState, useCallback, useRef, useEffect } from 'react';
import { Play, AlertCircle, Settings } from 'lucide-react';
import Prism from 'prismjs';
import 'prismjs/components/prism-latex';
import '../latex-highlight.css';

interface LaTeXEditorProps {
  content: string;
  onChange: (content: string) => void;
  onCompile: (compiler: string) => void;
  compiling: boolean;
  hasErrors: boolean;
}

export const LaTeXEditor: React.FC<LaTeXEditorProps> = ({
  content,
  onChange,
  onCompile,
  compiling,
  hasErrors,
}) => {
  const [lineNumbers, setLineNumbers] = useState<number[]>([]);
  const [compiler, setCompiler] = useState<'pdflatex' | 'xelatex'>('pdflatex');
  const [showCompilerMenu, setShowCompilerMenu] = useState(false);
  const lineRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const highlightRef = useRef<HTMLPreElement>(null);

  const updateLineNumbers = useCallback((text: string) => {
    const lines = text ? text.split('\n').length : 1;
    setLineNumbers(Array.from({ length: lines }, (_, i) => i + 1));
  }, []);

  useEffect(() => {
    updateLineNumbers(content);
  }, [content, updateLineNumbers]);

  // Highlight syntax when content changes
  useEffect(() => {
    if (highlightRef.current) {
      const highlighted = Prism.highlight(content || '', Prism.languages.latex, 'latex');
      highlightRef.current.innerHTML = highlighted + '\n';
    }
  }, [content]);

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newContent = e.target.value;
    onChange(newContent);
    updateLineNumbers(newContent);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const target = e.target as HTMLTextAreaElement;
      const start = target.selectionStart;
      const end = target.selectionEnd;
      const newContent = content.substring(0, start) + '  ' + content.substring(end);
      onChange(newContent);
      setTimeout(() => {
        target.selectionStart = target.selectionEnd = start + 2;
      }, 0);
    }
  };

  const handleScroll = () => {
    if (lineRef.current && textRef.current && highlightRef.current) {
      lineRef.current.scrollTop = textRef.current.scrollTop;
      highlightRef.current.scrollTop = textRef.current.scrollTop;
    }
  };

  const handleCompileClick = () => {
    onCompile(compiler);
    setShowCompilerMenu(false);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-gray-800 dark:to-gray-800">
        <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-blue-500"></span>
          LaTeX Editor
        </h3>
        <div className="flex items-center gap-2">
          <div className="relative">
            <button
              onClick={() => setShowCompilerMenu(!showCompilerMenu)}
              className="flex items-center gap-1 px-2 py-1 text-xs text-gray-600 dark:text-gray-300 hover:bg-white/50 dark:hover:bg-gray-700 rounded-md transition-colors"
              title="Compiler settings"
            >
              <Settings className="w-3.5 h-3.5" />
              <span>{compiler === 'pdflatex' ? 'pdfLaTeX' : 'XeLaTeX'}</span>
            </button>
            {showCompilerMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowCompilerMenu(false)} />
                <div className="absolute right-0 mt-2 w-44 bg-white dark:bg-gray-800 rounded-md shadow-lg z-20 border border-gray-200 dark:border-gray-600">
                  <div className="py-1">
                    <button
                      className={`w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 ${compiler === 'pdflatex' ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400' : 'text-gray-700 dark:text-gray-300'}`}
                      onClick={() => { setCompiler('pdflatex'); setShowCompilerMenu(false); }}
                    >
                      📄 pdfLaTeX
                    </button>
                    <button
                      className={`w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 ${compiler === 'xelatex' ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400' : 'text-gray-700 dark:text-gray-300'}`}
                      onClick={() => { setCompiler('xelatex'); setShowCompilerMenu(false); }}
                    >
                      🌐 XeLaTeX
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>

          {hasErrors && (
            <div className="flex items-center gap-1 text-red-500 text-xs font-medium bg-red-50 dark:bg-red-900/30 px-2 py-1 rounded-full">
              <AlertCircle className="w-3 h-3" />
              <span>Errors</span>
            </div>
          )}

          <button
            onClick={handleCompileClick}
            disabled={compiling}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition-all ${
              compiling
                ? 'bg-gray-200 dark:bg-gray-700 text-gray-400 cursor-not-allowed'
                : 'bg-blue-600 text-white hover:bg-blue-700 shadow-md hover:shadow-lg active:scale-95'
            }`}
          >
            {compiling ? (
              <div className="w-3.5 h-3.5 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5" />
            )}
            {compiling ? 'Compiling...' : 'Compile'}
          </button>
        </div>
      </div>

      {/* Editor with syntax highlighting */}
      <div className="flex flex-1 relative overflow-hidden">
        {/* Line numbers */}
        <div
          ref={lineRef}
          className="w-10 bg-gray-100 dark:bg-gray-900 border-r border-gray-200 dark:border-gray-700 text-right overflow-hidden select-none"
        >
          <div className="py-3">
            {lineNumbers.map((num) => (
              <div key={num} className="px-1.5 text-xs text-gray-400 dark:text-gray-600 leading-6">
                {num}
              </div>
            ))}
          </div>
        </div>

        {/* Editor area */}
        <div className="flex-1 relative bg-gradient-to-br from-blue-50 via-indigo-50 to-purple-50 dark:from-slate-950 dark:via-indigo-950 dark:to-blue-950">
          {/* Highlighted layer (behind) */}
          <pre
            ref={highlightRef}
            className="absolute inset-0 p-3 font-mono text-sm leading-6 whitespace-pre-wrap break-all overflow-hidden pointer-events-none bg-transparent"
            style={{ tabSize: 2 }}
          >
            <code className="language-latex">{content}</code>
          </pre>

          {/* Textarea layer (front, transparent text) */}
          <textarea
            ref={textRef}
            value={content || ''}
            onChange={handleTextChange}
            onKeyDown={handleKeyDown}
            onScroll={handleScroll}
            className="absolute inset-0 w-full h-full p-3 font-mono text-sm leading-6 border-none outline-none resize-none bg-transparent text-transparent caret-gray-800 dark:caret-gray-200"
            style={{ tabSize: 2 }}
            placeholder="Start typing your LaTeX document here..."
            spellCheck={false}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
          />
        </div>
      </div>
    </div>
  );
};