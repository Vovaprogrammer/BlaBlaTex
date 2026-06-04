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

const LINE_HEIGHT = 24; // px, must match CSS

// Shared style constants — applied identically to textarea, highlight pre, and ruler
const EDITOR_FONT_FAMILY =
  'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace';
const EDITOR_FONT_SIZE = '14px';
const EDITOR_PADDING = 12; // px, same on all sides

export const LaTeXEditor: React.FC<LaTeXEditorProps> = ({
  content,
  onChange,
  onCompile,
  compiling,
  hasErrors,
}) => {
  const [lineHeights, setLineHeights] = useState<number[]>([LINE_HEIGHT]);
  const [compiler, setCompiler] = useState<'pdflatex' | 'xelatex'>('pdflatex');
  const [showCompilerMenu, setShowCompilerMenu] = useState(false);

  const lineRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const highlightRef = useRef<HTMLPreElement>(null);
  const editorAreaRef = useRef<HTMLDivElement>(null);
  const rulerRef = useRef<HTMLDivElement>(null);

  // ── Ruler-based line height measurement ────────────────────────────────────
  const measureLineHeights = useCallback(() => {
    const ruler = rulerRef.current;
    const editorArea = editorAreaRef.current;
    if (!ruler || !editorArea) return;

    // Inner width of the editor area = total width minus the line-numbers column (40px) minus both paddings
    const innerWidth = editorArea.offsetWidth - 40 - EDITOR_PADDING * 2;
    if (innerWidth <= 0) return;

    ruler.style.width = `${innerWidth}px`;

    const lines = (content || '').split('\n');
    const heights: number[] = lines.map((line) => {
      ruler.textContent = line || '\u200B'; // zero-width space keeps height for empty lines
      return Math.max(ruler.offsetHeight, LINE_HEIGHT);
    });

    setLineHeights(heights);
  }, [content]);

  useEffect(() => {
    measureLineHeights();
  }, [measureLineHeights]);

  useEffect(() => {
    const el = editorAreaRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => measureLineHeights());
    ro.observe(el);
    return () => ro.disconnect();
  }, [measureLineHeights]);

  // ── Syntax highlight update ─────────────────────────────────────────────────
  useEffect(() => {
    if (!highlightRef.current) return;
    const highlighted = Prism.highlight(content || '', Prism.languages.latex, 'latex');
    // Extra newline so the pre never collapses shorter than the textarea
    highlightRef.current.innerHTML = highlighted + '\n';
  }, [content]);

  // ── Handlers ────────────────────────────────────────────────────────────────
  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onChange(e.target.value);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const ta = e.target as HTMLTextAreaElement;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const next = content.substring(0, start) + '  ' + content.substring(end);
      onChange(next);
      setTimeout(() => {
        ta.selectionStart = ta.selectionEnd = start + 2;
      }, 0);
    }
  };

  const handleScroll = () => {
    const ta = textRef.current;
    const ln = lineRef.current;
    const hl = highlightRef.current;
    if (!ta || !ln || !hl) return;
    ln.scrollTop = ta.scrollTop;
    hl.scrollTop = ta.scrollTop;
    hl.scrollLeft = ta.scrollLeft;
  };

  const handleCompileClick = () => {
    onCompile(compiler);
    setShowCompilerMenu(false);
  };

  // ── Shared inline styles for textarea AND highlight pre ────────────────────
  // Every property that affects text layout must be identical between the two.
  const sharedTextStyles: React.CSSProperties = {
    fontFamily: EDITOR_FONT_FAMILY,
    fontSize: EDITOR_FONT_SIZE,
    lineHeight: `${LINE_HEIGHT}px`,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    overflowWrap: 'break-word',
    tabSize: 2,
    padding: `${EDITOR_PADDING}px`,
    margin: 0,
    border: 'none',
    boxSizing: 'border-box' as const,
    letterSpacing: 'normal',
    wordSpacing: 'normal',
  };

  return (
    <div className="flex flex-col h-full">
      {/* ── Header ── */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-gradient-to-r from-slate-300 via-blue-300 to-indigo-300 dark:from-gray-800 dark:to-gray-800">
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
                      className={`w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 ${
                        compiler === 'pdflatex'
                          ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400'
                          : 'text-gray-700 dark:text-gray-300'
                      }`}
                      onClick={() => { setCompiler('pdflatex'); setShowCompilerMenu(false); }}
                    >
                      📄 pdfLaTeX
                    </button>
                    <button
                      className={`w-full px-4 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-700 ${
                        compiler === 'xelatex'
                          ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400'
                          : 'text-gray-700 dark:text-gray-300'
                      }`}
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
                ? 'bg-gray-400 text-gray-600 cursor-not-allowed'
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

      {/* ── Editor body ── */}
      <div className="flex flex-1 relative overflow-hidden" ref={editorAreaRef}>

        {/* Hidden ruler — measures wrapped line heights */}
        <div
          ref={rulerRef}
          aria-hidden="true"
          style={{
            position: 'fixed',
            top: 0,
            left: '-99999px',
            visibility: 'hidden',
            pointerEvents: 'none',
            fontFamily: EDITOR_FONT_FAMILY,
            fontSize: EDITOR_FONT_SIZE,
            lineHeight: `${LINE_HEIGHT}px`,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            overflowWrap: 'break-word',
            tabSize: 2,
            padding: 0,
            margin: 0,
            border: 'none',
            boxSizing: 'border-box',
          }}
        />

        {/* Line numbers */}
        <div
          ref={lineRef}
          className="bg-gradient-to-b from-slate-300 via-blue-300 to-indigo-300 dark:bg-gradient-to-b dark:from-gray-900 dark:via-gray-900 dark:to-gray-900 border-r border-gray-200 dark:border-gray-700 select-none flex-shrink-0"
          style={{
            width: '40px',
            paddingTop: `${EDITOR_PADDING}px`,
            overflowY: 'hidden',
            overflowX: 'hidden',
          }}
        >
          {lineHeights.map((h, i) => (
            <div
              key={i}
              className="text-right px-1.5 text-xs text-gray-500 dark:text-gray-600 flex items-start justify-end"
              style={{
                height: `${h}px`,
                minHeight: `${LINE_HEIGHT}px`,
                // Align number to top of the first visual line
                paddingTop: `${(LINE_HEIGHT - 16) / 2}px`,
                boxSizing: 'border-box',
              }}
            >
              {i + 1}
            </div>
          ))}
        </div>

        {/* Text area */}
        <div
          className="flex-1 relative bg-gradient-to-br from-slate-300 via-blue-300 to-indigo-300 dark:from-slate-950 dark:via-indigo-950 dark:to-blue-950 overflow-hidden"
        >
          {/* Syntax highlight layer — MUST have identical layout styles to textarea */}
          <pre
            ref={highlightRef}
            aria-hidden="true"
            className="absolute inset-0 pointer-events-none bg-transparent overflow-hidden"
            style={{
              ...sharedTextStyles,
              width: '100%',
              height: '100%',
              // override overflow so it stays locked to textarea scroll
              overflow: 'hidden',
            }}
          >
            <code className="language-latex" />
          </pre>

          {/* Textarea — the single source of truth for cursor position */}
          <textarea
            ref={textRef}
            value={content || ''}
            onChange={handleTextChange}
            onKeyDown={handleKeyDown}
            onScroll={handleScroll}
            className="absolute inset-0 w-full h-full outline-none resize-none bg-transparent text-transparent caret-gray-800 dark:caret-gray-200"
            style={{
              ...sharedTextStyles,
              overflow: 'auto',
              // text is invisible — highlight layer shows it; caret stays visible
              color: 'transparent',
            }}
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
