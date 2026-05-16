import React, { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import {
  Wand2,
  HelpCircle,
  Calculator,
  Table,
  BarChart3,
  Palette,
  Book,
  Send,
  Loader2,
  Copy,
  CheckCircle,
  AlertCircle,
  TrendingUp,
  Shield,
  Users,
  Settings,
  FileText,
  Sigma,
  Puzzle
} from 'lucide-react';

const API_BASE_URL = 'http://localhost:8000';

interface AIAssistantProps {
  onInsertCode: (code: string) => void;
}

// ============================================
// MARKDOWN RENDERER COMPONENT
// ============================================
const MarkdownRenderer: React.FC<{ content: string }> = ({ content }) => {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none">
      <ReactMarkdown
        remarkPlugins={[remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '');
            const isInline = !match && !className;
            if (isInline) {
              return (
                <code className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-800 rounded text-sm font-mono text-pink-600 dark:text-pink-400" {...props}>
                  {children}
                </code>
              );
            }
            return (
              <pre className="p-3 bg-gray-100 dark:bg-gray-800 rounded-md overflow-x-auto my-2 border border-gray-200 dark:border-gray-700">
                <code className={`text-sm font-mono ${match ? `language-${match[1]}` : ''}`}>
                  {children}
                </code>
              </pre>
            );
          },
          p({ children }) {
            return <p className="mb-2 last:mb-0 leading-relaxed text-gray-800 dark:text-gray-200">{children}</p>;
          },
          ul({ children }) {
            return <ul className="list-disc pl-5 mb-2 space-y-1">{children}</ul>;
          },
          ol({ children }) {
            return <ol className="list-decimal pl-5 mb-2 space-y-1">{children}</ol>;
          },
          li({ children }) {
            return <li className="text-gray-700 dark:text-gray-300">{children}</li>;
          },
          h3({ children }) {
            return <h3 className="text-base font-semibold mt-3 mb-1 text-gray-800 dark:text-gray-200">{children}</h3>;
          },
          strong({ children }) {
            return <strong className="font-semibold text-gray-900 dark:text-white">{children}</strong>;
          },
          em({ children }) {
            return <em className="italic text-gray-700 dark:text-gray-300">{children}</em>;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

// ============================================
// RESULT DISPLAY COMPONENTS
// ============================================

// For LaTeX code blocks (with Copy + Insert buttons)
const LatexResult: React.FC<{ content: string; onInsert: (code: string) => void; copied: string; onCopy: (text: string) => void }> = ({ content, onInsert, copied, onCopy }) => (
  <div className="mt-3 relative">
    <pre className="p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md text-sm font-mono whitespace-pre-wrap break-words max-h-64 overflow-auto leading-relaxed">{content}</pre>
    <div className="flex gap-2 mt-2">
      <button onClick={() => onCopy(content)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
        {copied === content ? <CheckCircle className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
        {copied === content ? 'Copied!' : 'Copy'}
      </button>
      <button onClick={() => onInsert(content)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors">
        <Send className="w-4 h-4" />
        Insert
      </button>
    </div>
  </div>
);

// For Markdown-rendered content (with Copy button only)
const MarkdownResult: React.FC<{ content: string; copied: string; onCopy: (text: string) => void }> = ({ content, copied, onCopy }) => (
  <div className="mt-3 relative">
    <MarkdownRenderer content={content} />
    <button onClick={() => onCopy(content)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors mt-2">
      {copied === content ? <CheckCircle className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
      {copied === content ? 'Copied!' : 'Copy'}
    </button>
  </div>
);

// For plain text results (with Copy button only)
const PlainTextResult: React.FC<{ content: string; copied: string; onCopy: (text: string) => void }> = ({ content, copied, onCopy }) => (
  <div className="mt-3 relative">
    <pre className="p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md text-sm whitespace-pre-wrap break-words max-h-64 overflow-auto leading-relaxed">{content}</pre>
    <button onClick={() => onCopy(content)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors mt-2">
      {copied === content ? <CheckCircle className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
      {copied === content ? 'Copied!' : 'Copy'}
    </button>
  </div>
);


export const AIAssistant: React.FC<AIAssistantProps> = ({ onInsertCode }) => {
  const [activeTab, setActiveTab] = useState<'generate' | 'explain' | 'math' | 'figures' | 'references' | 'accessibility' | 'collaboration'>('generate');

  // Generate states
  const [documentPrompt, setDocumentPrompt] = useState('');
  const [documentResult, setDocumentResult] = useState('');
  const [documentLoading, setDocumentLoading] = useState(false);
  const [documentError, setDocumentError] = useState('');

  const [formulaPrompt, setFormulaPrompt] = useState('');
  const [formulaResult, setFormulaResult] = useState('');
  const [formulaLoading, setFormulaLoading] = useState(false);
  const [formulaError, setFormulaError] = useState('');

  const [partPrompt, setPartPrompt] = useState('');
  const [partType, setPartType] = useState('section');
  const [partResult, setPartResult] = useState('');
  const [partLoading, setPartLoading] = useState(false);
  const [partError, setPartError] = useState('');

  // Explain states
  const [codeToExplain, setCodeToExplain] = useState('');
  const [codeExplainResult, setCodeExplainResult] = useState('');
  const [codeExplainLoading, setCodeExplainLoading] = useState(false);
  const [codeExplainError, setCodeExplainError] = useState('');

  const [latexQuestion, setLatexQuestion] = useState('');
  const [latexExplainResult, setLatexExplainResult] = useState('');
  const [latexExplainLoading, setLatexExplainLoading] = useState(false);
  const [latexExplainError, setLatexExplainError] = useState('');

  // Math states
  const [mathSolveInput, setMathSolveInput] = useState('');
  const [mathSolveResult, setMathSolveResult] = useState('');
  const [mathSolveLoading, setMathSolveLoading] = useState(false);
  const [mathSolveError, setMathSolveError] = useState('');

  const [mathDeriveInput, setMathDeriveInput] = useState('');
  const [mathDeriveResult, setMathDeriveResult] = useState('');
  const [mathDeriveLoading, setMathDeriveLoading] = useState(false);
  const [mathDeriveError, setMathDeriveError] = useState('');
  const [mathDeriveOperation, setMathDeriveOperation] = useState('derive');

  const [mathPhysicsInput, setMathPhysicsInput] = useState('');
  const [mathPhysicsResult, setMathPhysicsResult] = useState('');
  const [mathPhysicsLoading, setMathPhysicsLoading] = useState(false);
  const [mathPhysicsError, setMathPhysicsError] = useState('');

  const [mathCheckInput, setMathCheckInput] = useState('');
  const [mathCheckResult, setMathCheckResult] = useState('');
  const [mathCheckLoading, setMathCheckLoading] = useState(false);
  const [mathCheckError, setMathCheckError] = useState('');

  // Figures states
  const [tableInput, setTableInput] = useState('');
  const [tableHasHeader, setTableHasHeader] = useState(true);
  const [tableUseBooktabs, setTableUseBooktabs] = useState(true);
  const [tableResult, setTableResult] = useState('');
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState('');

  const [diagramInput, setDiagramInput] = useState('');
  const [diagramResult, setDiagramResult] = useState('');
  const [diagramLoading, setDiagramLoading] = useState(false);
  const [diagramError, setDiagramError] = useState('');

  const [plotExpression, setPlotExpression] = useState('');
  const [plotXlabel, setPlotXlabel] = useState('x');
  const [plotYlabel, setPlotYlabel] = useState('y');
  const [plotTitle, setPlotTitle] = useState('');
  const [plotResult, setPlotResult] = useState('');
  const [plotLoading, setPlotLoading] = useState(false);
  const [plotError, setPlotError] = useState('');

  // References states
  const [refIdentifier, setRefIdentifier] = useState('');
  const [refResult, setRefResult] = useState('');
  const [refLoading, setRefLoading] = useState(false);
  const [refError, setRefError] = useState('');

  const [formatRefInput, setFormatRefInput] = useState('');
  const [formatRefStyle, setFormatRefStyle] = useState('ieee');
  const [formatRefResult, setFormatRefResult] = useState('');
  const [formatRefLoading, setFormatRefLoading] = useState(false);
  const [formatRefError, setFormatRefError] = useState('');

  const [checkCitationInput, setCheckCitationInput] = useState('');
  const [checkCitationResult, setCheckCitationResult] = useState('');
  const [checkCitationLoading, setCheckCitationLoading] = useState(false);
  const [checkCitationError, setCheckCitationError] = useState('');

  // Accessibility states
  const [altTextInput, setAltTextInput] = useState('');
  const [altTextResult, setAltTextResult] = useState('');
  const [altTextLoading, setAltTextLoading] = useState(false);
  const [altTextError, setAltTextError] = useState('');

  const [colorInput, setColorInput] = useState('');
  const [colorPalette, setColorPalette] = useState('all');
  const [colorResult, setColorResult] = useState('');
  const [colorLoading, setColorLoading] = useState(false);
  const [colorError, setColorError] = useState('');

  const [templateInput, setTemplateInput] = useState('');
  const [templateType, setTemplateType] = useState('ieee');
  const [templateResult, setTemplateResult] = useState('');
  const [templateLoading, setTemplateLoading] = useState(false);
  const [templateError, setTemplateError] = useState('');

  // Collaboration states
  const [diffOldText, setDiffOldText] = useState('');
  const [diffNewText, setDiffNewText] = useState('');
  const [diffResult, setDiffResult] = useState('');
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState('');

  const [summarizeOldText, setSummarizeOldText] = useState('');
  const [summarizeNewText, setSummarizeNewText] = useState('');
  const [summarizeResult, setSummarizeResult] = useState('');
  const [summarizeLoading, setSummarizeLoading] = useState(false);
  const [summarizeError, setSummarizeError] = useState('');

  const [summarizeDocInput, setSummarizeDocInput] = useState('');
  const [summarizeDocResult, setSummarizeDocResult] = useState('');
  const [summarizeDocLoading, setSummarizeDocLoading] = useState(false);
  const [summarizeDocError, setSummarizeDocError] = useState('');

  const [copied, setCopied] = useState('');

  const handleStreamResponse = async (
      url: string,
      body: any,
      setResult: (val: string) => void,
      setLoading: (val: boolean) => void,
      setError: (val: string) => void
  ) => {
      setLoading(true);
      setError('');
      setResult('');

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 300000);

      try {
          const response = await fetch(`${API_BASE_URL}${url}`, {
              method: 'POST',
              headers: {
                  'Content-Type': 'application/json',
                  'Accept': 'text/event-stream'
              },
              body: JSON.stringify(body),
              signal: controller.signal
          });

          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          if (!response.body) throw new Error('No response body');

          const reader = response.body.getReader();
          const decoder = new TextDecoder('utf-8');
          let accumulatedText = '';
          let buffer = '';

          while (true) {
              const { done, value } = await reader.read();
              if (done) break;

              buffer += decoder.decode(value, { stream: true });
              const events = buffer.split('\n\n');
              buffer = events.pop() || '';

              for (const event of events) {
                  const lines = event.split('\n');
                  for (const line of lines) {
                      if (!line.startsWith('data: ')) continue;
                      const jsonStr = line.slice(6);
                      try {
                          const data = JSON.parse(jsonStr);
                          if (data.error) { setError(data.error); continue; }
                          if (data.token !== undefined) {
                              accumulatedText += data.token;
                              const fixed = accumulatedText
                              setResult(fixed);
                          }
                          if (data.done) { setLoading(false); return; }
                      } catch (err) { console.error('JSON parse error:', err); }
                  }
              }
          }
      } catch (err: any) {
          if (err.name === 'AbortError') setError('Request timed out');
          else setError(err.message || 'Request failed');
      } finally {
          clearTimeout(timeoutId);
          setLoading(false);
      }
  };

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(text);
      setTimeout(() => setCopied(''), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const tabs = [
    { id: 'generate', label: 'Generate', icon: Wand2 },
    { id: 'explain', label: 'Explain', icon: HelpCircle },
    { id: 'math', label: 'Math', icon: Calculator },
    { id: 'figures', label: 'Figures', icon: BarChart3 },
    { id: 'references', label: 'References', icon: Book },
    { id: 'accessibility', label: 'Accessibility', icon: Shield },
    { id: 'collaboration', label: 'Collaboration', icon: Users },
  ] as const;

  return (
    <div className="flex flex-col h-full bg-white dark:bg-gray-900 border-l border-gray-200 dark:border-gray-700">
      {/* Header */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">AI Assistant</h2>
          <div className="flex items-center gap-2">
            <Settings className="w-4 h-4 text-gray-400" />
            <span className="text-xs text-gray-500 dark:text-gray-400 font-medium px-2 py-1 bg-gray-100 dark:bg-gray-700 rounded-lg">
              Powered by Llama 3.1 8B + Qwen 80B
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-1 mb-2">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                activeTab === id
                  ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300'
                  : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800'
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 p-4 overflow-y-auto space-y-6">
        {/* ========== GENERATE TAB ========== */}
        {activeTab === 'generate' && (
          <>
            {/* Generate Full Document */}
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                <FileText className="w-4 h-4" />
                Generate Full Document
              </h3>
              <textarea
                value={documentPrompt}
                onChange={(e) => setDocumentPrompt(e.target.value)}
                placeholder="E.g., Create an article about Newton's laws..."
                className="w-full h-24 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm"
              />
              <button
                onClick={() => handleStreamResponse('/ai/generate/document', { description: documentPrompt }, setDocumentResult, setDocumentLoading, setDocumentError)}
                disabled={documentLoading || !documentPrompt.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm"
              >
                {documentLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
                {documentLoading ? 'Generating...' : 'Generate Document'}
              </button>
              {documentError && <p className="text-red-500 text-sm mt-2">{documentError}</p>}
              {documentResult && <LatexResult content={documentResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>

            {/* Generate Formula */}
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                <Sigma className="w-4 h-4" />
                Generate Formula
              </h3>
              <textarea
                value={formulaPrompt}
                onChange={(e) => setFormulaPrompt(e.target.value)}
                placeholder="E.g., Einstein's mass-energy equivalence..."
                className="w-full h-20 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm"
              />
              <button
                onClick={() => handleStreamResponse('/ai/generate/formula', { description: formulaPrompt }, setFormulaResult, setFormulaLoading, setFormulaError)}
                disabled={formulaLoading || !formulaPrompt.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm"
              >
                {formulaLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sigma className="w-4 h-4" />}
                {formulaLoading ? 'Generating...' : 'Generate Formula'}
              </button>
              {formulaError && <p className="text-red-500 text-sm mt-2">{formulaError}</p>}
              {formulaResult && <LatexResult content={formulaResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>

            {/* Generate Part */}
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                <Puzzle className="w-4 h-4" />
                Generate Part
              </h3>
              <div className="flex gap-2 mb-2">
                <select value={partType} onChange={(e) => setPartType(e.target.value)} className="p-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-sm">
                  <option value="section">Section</option>
                  <option value="theorem">Theorem</option>
                  <option value="proof">Proof</option>
                  <option value="definition">Definition</option>
                  <option value="example">Example</option>
                </select>
              </div>
              <textarea
                value={partPrompt}
                onChange={(e) => setPartPrompt(e.target.value)}
                placeholder="E.g., Explain the concept of limits in calculus..."
                className="w-full h-20 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm"
              />
              <button
                onClick={() => handleStreamResponse('/ai/generate/part', { description: partPrompt, part_type: partType }, setPartResult, setPartLoading, setPartError)}
                disabled={partLoading || !partPrompt.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-md hover:bg-teal-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm"
              >
                {partLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Puzzle className="w-4 h-4" />}
                {partLoading ? 'Generating...' : `Generate ${partType}`}
              </button>
              {partError && <p className="text-red-500 text-sm mt-2">{partError}</p>}
              {partResult && <LatexResult content={partResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>
          </>
        )}

        {/* ========== EXPLAIN TAB ========== */}
        {activeTab === 'explain' && (
          <>
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                <FileText className="w-4 h-4" />
                Explain Code
              </h3>
              <textarea
                value={codeToExplain}
                onChange={(e) => setCodeToExplain(e.target.value)}
                placeholder="Paste your LaTeX code here..."
                className="w-full h-24 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm"
              />
              <button
                onClick={() => handleStreamResponse('/ai/explain/code', { code: codeToExplain }, setCodeExplainResult, setCodeExplainLoading, setCodeExplainError)}
                disabled={codeExplainLoading || !codeToExplain.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm"
              >
                {codeExplainLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <HelpCircle className="w-4 h-4" />}
                {codeExplainLoading ? 'Explaining...' : 'Explain Code'}
              </button>
              {codeExplainError && <p className="text-red-500 text-sm mt-2">{codeExplainError}</p>}
              {codeExplainResult && <MarkdownResult content={codeExplainResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                <HelpCircle className="w-4 h-4" />
                Ask LaTeX Question
              </h3>
              <textarea
                value={latexQuestion}
                onChange={(e) => setLatexQuestion(e.target.value)}
                placeholder="E.g., How to center text in LaTeX?"
                className="w-full h-20 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm"
              />
              <button
                onClick={() => handleStreamResponse('/ai/explain/latex', { question: latexQuestion }, setLatexExplainResult, setLatexExplainLoading, setLatexExplainError)}
                disabled={latexExplainLoading || !latexQuestion.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-yellow-600 text-white rounded-md hover:bg-yellow-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm"
              >
                {latexExplainLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <HelpCircle className="w-4 h-4" />}
                {latexExplainLoading ? 'Asking...' : 'Ask Question'}
              </button>
              {latexExplainError && <p className="text-red-500 text-sm mt-2">{latexExplainError}</p>}
              {latexExplainResult && <MarkdownResult content={latexExplainResult} copied={copied} onCopy={copyToClipboard} />}
            </div>
          </>
        )}

        {/* ========== MATH TAB ========== */}
        {activeTab === 'math' && (
          <>
            {/* Solve Equation */}
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                <TrendingUp className="w-4 h-4" />
                Solve Equation
              </h3>
              <textarea
                value={mathSolveInput}
                onChange={(e) => setMathSolveInput(e.target.value)}
                placeholder="E.g., x^2 + 2x + 1 = 0"
                className="w-full h-16 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm"
              />
              <button
                onClick={() => handleStreamResponse('/ai/math/solve', { equation: mathSolveInput }, setMathSolveResult, setMathSolveLoading, setMathSolveError)}
                disabled={mathSolveLoading || !mathSolveInput.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm"
              >
                {mathSolveLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <TrendingUp className="w-4 h-4" />}
                {mathSolveLoading ? 'Solving...' : 'Solve'}
              </button>
              {mathSolveError && <p className="text-red-500 text-sm mt-2">{mathSolveError}</p>}
              {mathSolveResult && <MarkdownResult content={mathSolveResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            {/* Derive/Integrate */}
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                <Sigma className="w-4 h-4" />
                Calculus
              </h3>
              <div className="flex gap-2 mb-2">
                <select value={mathDeriveOperation} onChange={(e) => setMathDeriveOperation(e.target.value)} className="p-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-sm">
                  <option value="derive">Derive (производная)</option>
                  <option value="integrate">Integrate (интеграл)</option>
                </select>
              </div>
              <textarea
                value={mathDeriveInput}
                onChange={(e) => setMathDeriveInput(e.target.value)}
                placeholder="E.g., x^3 + 2x^2 + 5x"
                className="w-full h-16 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm"
              />
              <button
                onClick={() => handleStreamResponse('/ai/math/derive', { expression: mathDeriveInput, operation: mathDeriveOperation }, setMathDeriveResult, setMathDeriveLoading, setMathDeriveError)}
                disabled={mathDeriveLoading || !mathDeriveInput.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm"
              >
                {mathDeriveLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sigma className="w-4 h-4" />}
                {mathDeriveLoading ? 'Calculating...' : mathDeriveOperation === 'derive' ? 'Derive' : 'Integrate'}
              </button>
              {mathDeriveError && <p className="text-red-500 text-sm mt-2">{mathDeriveError}</p>}
              {mathDeriveResult && <MarkdownResult content={mathDeriveResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            {/* Physics Formula */}
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                <Calculator className="w-4 h-4" />
                Physics Formula
              </h3>
              <textarea
                value={mathPhysicsInput}
                onChange={(e) => setMathPhysicsInput(e.target.value)}
                placeholder="E.g., Express velocity from E = mv^2/2"
                className="w-full h-16 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm"
              />
              <button
                onClick={() => handleStreamResponse('/ai/math/physics', { description: mathPhysicsInput }, setMathPhysicsResult, setMathPhysicsLoading, setMathPhysicsError)}
                disabled={mathPhysicsLoading || !mathPhysicsInput.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-cyan-600 text-white rounded-md hover:bg-cyan-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm"
              >
                {mathPhysicsLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Calculator className="w-4 h-4" />}
                {mathPhysicsLoading ? 'Calculating...' : 'Solve'}
              </button>
              {mathPhysicsError && <p className="text-red-500 text-sm mt-2">{mathPhysicsError}</p>}
              {mathPhysicsResult && <MarkdownResult content={mathPhysicsResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            {/* Check Formula */}
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                <Shield className="w-4 h-4" />
                Check Formula
              </h3>
              <textarea
                value={mathCheckInput}
                onChange={(e) => setMathCheckInput(e.target.value)}
                placeholder="E.g., E = mc^3"
                className="w-full h-16 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm"
              />
              <button
                onClick={() => handleStreamResponse('/ai/math/check', { formula: mathCheckInput }, setMathCheckResult, setMathCheckLoading, setMathCheckError)}
                disabled={mathCheckLoading || !mathCheckInput.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-orange-600 text-white rounded-md hover:bg-orange-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm"
              >
                {mathCheckLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Shield className="w-4 h-4" />}
                {mathCheckLoading ? 'Checking...' : 'Check'}
              </button>
              {mathCheckError && <p className="text-red-500 text-sm mt-2">{mathCheckError}</p>}
              {mathCheckResult && <MarkdownResult content={mathCheckResult} copied={copied} onCopy={copyToClipboard} />}
            </div>
          </>
        )}

        {/* ========== FIGURES TAB ========== */}
        {activeTab === 'figures' && (
          <>
            {/* Generate Table */}
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                <Table className="w-4 h-4" />
                Generate Table
              </h3>
              <div className="flex gap-2 mb-2">
                <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={tableHasHeader} onChange={(e) => setTableHasHeader(e.target.checked)} />Header</label>
                <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={tableUseBooktabs} onChange={(e) => setTableUseBooktabs(e.target.checked)} />Booktabs</label>
              </div>
              <textarea value={tableInput} onChange={(e) => setTableInput(e.target.value)} placeholder="Name,Score\nAlice,95" className="w-full h-24 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm font-mono" />
              <button onClick={() => handleStreamResponse('/ai/figures/table', { csv: tableInput, has_header: tableHasHeader, use_booktabs: tableUseBooktabs }, setTableResult, setTableLoading, setTableError)} disabled={tableLoading || !tableInput.trim()} className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm">
                {tableLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Table className="w-4 h-4" />}
                {tableLoading ? 'Generating...' : 'Generate Table'}
              </button>
              {tableError && <p className="text-red-500 text-sm mt-2">{tableError}</p>}
              {tableResult && <LatexResult content={tableResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>

            {/* Generate Diagram */}
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><BarChart3 className="w-4 h-4" />Generate Diagram</h3>
              <textarea value={diagramInput} onChange={(e) => setDiagramInput(e.target.value)} placeholder="Describe the diagram..." className="w-full h-24 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm" />
              <button onClick={() => handleStreamResponse('/ai/figures/diagram', { prompt: diagramInput }, setDiagramResult, setDiagramLoading, setDiagramError)} disabled={diagramLoading || !diagramInput.trim()} className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-md hover:bg-teal-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm">
                {diagramLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />}
                {diagramLoading ? 'Generating...' : 'Generate Diagram'}
              </button>
              {diagramError && <p className="text-red-500 text-sm mt-2">{diagramError}</p>}
              {diagramResult && <LatexResult content={diagramResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>

            {/* Generate Plot */}
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><TrendingUp className="w-4 h-4" />Generate Plot</h3>
              <div className="grid grid-cols-2 gap-2 mb-2">
                <input type="text" value={plotXlabel} onChange={(e) => setPlotXlabel(e.target.value)} placeholder="X label" className="p-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-sm" />
                <input type="text" value={plotYlabel} onChange={(e) => setPlotYlabel(e.target.value)} placeholder="Y label" className="p-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-sm" />
                <input type="text" value={plotTitle} onChange={(e) => setPlotTitle(e.target.value)} placeholder="Title (optional)" className="p-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-sm col-span-2" />
              </div>
              <textarea value={plotExpression} onChange={(e) => setPlotExpression(e.target.value)} placeholder="E.g., x^2" className="w-full h-20 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm" />
              <button onClick={() => handleStreamResponse('/ai/figures/plot', { expression: plotExpression, xlabel: plotXlabel, ylabel: plotYlabel, title: plotTitle }, setPlotResult, setPlotLoading, setPlotError)} disabled={plotLoading || !plotExpression.trim()} className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-orange-600 text-white rounded-md hover:bg-orange-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm">
                {plotLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <TrendingUp className="w-4 h-4" />}
                {plotLoading ? 'Generating...' : 'Generate Plot'}
              </button>
              {plotError && <p className="text-red-500 text-sm mt-2">{plotError}</p>}
              {plotResult && <LatexResult content={plotResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>
          </>
        )}

        {/* ========== REFERENCES TAB ========== */}
        {activeTab === 'references' && (
          <>
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Book className="w-4 h-4" />Fetch BibTeX</h3>
              <input type="text" value={refIdentifier} onChange={(e) => setRefIdentifier(e.target.value)} placeholder="e.g., 10.1000/xyz123" className="w-full p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm" />
              <button onClick={() => handleStreamResponse('/ai/references/fetch', { identifier: refIdentifier }, setRefResult, setRefLoading, setRefError)} disabled={refLoading || !refIdentifier.trim()} className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-cyan-600 text-white rounded-md hover:bg-cyan-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm">
                {refLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Book className="w-4 h-4" />}
                {refLoading ? 'Fetching...' : 'Fetch BibTeX'}
              </button>
              {refError && <p className="text-red-500 text-sm mt-2">{refError}</p>}
              {refResult && <LatexResult content={refResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Book className="w-4 h-4" />Format References</h3>
              <div className="flex gap-2 mb-2">
                <select value={formatRefStyle} onChange={(e) => setFormatRefStyle(e.target.value)} className="p-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-sm">
                  <option value="ieee">IEEE</option><option value="gost">ГОСТ</option><option value="apa">APA</option>
                </select>
              </div>
              <textarea value={formatRefInput} onChange={(e) => setFormatRefInput(e.target.value)} placeholder="Paste references..." className="w-full h-24 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm" />
              <button onClick={() => handleStreamResponse('/ai/references/format', { references: formatRefInput, style: formatRefStyle }, setFormatRefResult, setFormatRefLoading, setFormatRefError)} disabled={formatRefLoading || !formatRefInput.trim()} className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm">
                {formatRefLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Book className="w-4 h-4" />}
                {formatRefLoading ? 'Formatting...' : 'Format References'}
              </button>
              {formatRefError && <p className="text-red-500 text-sm mt-2">{formatRefError}</p>}
              {formatRefResult && <LatexResult content={formatRefResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><CheckCircle className="w-4 h-4" />Check Citation</h3>
              <textarea value={checkCitationInput} onChange={(e) => setCheckCitationInput(e.target.value)} placeholder="Paste BibTeX entry..." className="w-full h-24 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm" />
              <button onClick={() => handleStreamResponse('/ai/references/check', { citation: checkCitationInput }, setCheckCitationResult, setCheckCitationLoading, setCheckCitationError)} disabled={checkCitationLoading || !checkCitationInput.trim()} className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm">
                {checkCitationLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
                {checkCitationLoading ? 'Checking...' : 'Check Citation'}
              </button>
              {checkCitationError && <p className="text-red-500 text-sm mt-2">{checkCitationError}</p>}
              {checkCitationResult && <MarkdownResult content={checkCitationResult} copied={copied} onCopy={copyToClipboard} />}
            </div>
          </>
        )}

        {/* ========== ACCESSIBILITY TAB ========== */}
        {activeTab === 'accessibility' && (
          <>
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Shield className="w-4 h-4" />Generate Alt Text</h3>
              <textarea value={altTextInput} onChange={(e) => setAltTextInput(e.target.value)} placeholder="Paste figure/formula..." className="w-full h-24 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm" />
              <button onClick={() => handleStreamResponse('/ai/accessibility/alt-text', { figure_code: altTextInput }, setAltTextResult, setAltTextLoading, setAltTextError)} disabled={altTextLoading || !altTextInput.trim()} className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm">
                {altTextLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Shield className="w-4 h-4" />}
                {altTextLoading ? 'Generating...' : 'Generate Alt Text'}
              </button>
              {altTextError && <p className="text-red-500 text-sm mt-2">{altTextError}</p>}
              {altTextResult && <PlainTextResult content={altTextResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Palette className="w-4 h-4" />Check Colors</h3>
              <div className="flex gap-2 mb-2">
                <select value={colorPalette} onChange={(e) => setColorPalette(e.target.value)} className="p-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-sm">
                  <option value="all">All types</option><option value="protanopia">Protanopia</option><option value="deuteranopia">Deuteranopia</option><option value="tritanopia">Tritanopia</option>
                </select>
              </div>
              <textarea value={colorInput} onChange={(e) => setColorInput(e.target.value)} placeholder="#FF0000, #00FF00" className="w-full h-20 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm" />
              <button onClick={() => handleStreamResponse('/ai/accessibility/check-colors', { colors: colorInput.split(',').map(c => c.trim()), palette_type: colorPalette }, setColorResult, setColorLoading, setColorError)} disabled={colorLoading || !colorInput.trim()} className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm">
                {colorLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Palette className="w-4 h-4" />}
                {colorLoading ? 'Checking...' : 'Check Colors'}
              </button>
              {colorError && <p className="text-red-500 text-sm mt-2">{colorError}</p>}
              {colorResult && <PlainTextResult content={colorResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><CheckCircle className="w-4 h-4" />Check Template</h3>
              <div className="flex gap-2 mb-2">
                <select value={templateType} onChange={(e) => setTemplateType(e.target.value)} className="p-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-sm">
                  <option value="ieee">IEEE</option><option value="acm">ACM</option><option value="gost">ГОСТ</option>
                </select>
              </div>
              <textarea value={templateInput} onChange={(e) => setTemplateInput(e.target.value)} placeholder="Paste LaTeX document..." className="w-full h-24 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm" />
              <button onClick={() => handleStreamResponse('/ai/accessibility/check-template', { latex_code: templateInput, template: templateType }, setTemplateResult, setTemplateLoading, setTemplateError)} disabled={templateLoading || !templateInput.trim()} className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm">
                {templateLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
                {templateLoading ? 'Checking...' : 'Check Template'}
              </button>
              {templateError && <p className="text-red-500 text-sm mt-2">{templateError}</p>}
              {templateResult && <PlainTextResult content={templateResult} copied={copied} onCopy={copyToClipboard} />}
            </div>
          </>
        )}

        {/* ========== COLLABORATION TAB ========== */}
        {activeTab === 'collaboration' && (
          <>
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Users className="w-4 h-4" />Get Diff</h3>
              <p className="text-xs text-gray-500 mb-2">Compare two versions and see what changed.</p>
              <textarea value={diffOldText} onChange={(e) => setDiffOldText(e.target.value)} placeholder="Old version..." className="w-full h-24 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm mb-2" />
              <textarea value={diffNewText} onChange={(e) => setDiffNewText(e.target.value)} placeholder="New version..." className="w-full h-24 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm" />
              <button onClick={() => handleStreamResponse('/ai/collaboration/diff', { old_text: diffOldText, new_text: diffNewText }, setDiffResult, setDiffLoading, setDiffError)} disabled={diffLoading || !diffOldText.trim() || !diffNewText.trim()} className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm">
                {diffLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Users className="w-4 h-4" />}
                {diffLoading ? 'Comparing...' : 'Get Diff'}
              </button>
              {diffError && <p className="text-red-500 text-sm mt-2">{diffError}</p>}
              {diffResult && <MarkdownResult content={diffResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><FileText className="w-4 h-4" />Summarize Changes</h3>
              <p className="text-xs text-gray-500 mb-2">Get a human-readable summary of changes.</p>
              <textarea value={summarizeOldText} onChange={(e) => setSummarizeOldText(e.target.value)} placeholder="Old version..." className="w-full h-24 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm mb-2" />
              <textarea value={summarizeNewText} onChange={(e) => setSummarizeNewText(e.target.value)} placeholder="New version..." className="w-full h-24 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm" />
              <button onClick={() => handleStreamResponse('/ai/collaboration/summarize', { old_text: summarizeOldText, new_text: summarizeNewText }, setSummarizeResult, setSummarizeLoading, setSummarizeError)} disabled={summarizeLoading || !summarizeOldText.trim() || !summarizeNewText.trim()} className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm">
                {summarizeLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
                {summarizeLoading ? 'Summarizing...' : 'Summarize Changes'}
              </button>
              {summarizeError && <p className="text-red-500 text-sm mt-2">{summarizeError}</p>}
              {summarizeResult && <MarkdownResult content={summarizeResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Book className="w-4 h-4" />Summarize Document</h3>
              <p className="text-xs text-gray-500 mb-2">Create a concise summary of a full LaTeX document.</p>
              <textarea value={summarizeDocInput} onChange={(e) => setSummarizeDocInput(e.target.value)} placeholder="Paste your full LaTeX document..." className="w-full h-32 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm" />
              <button onClick={() => handleStreamResponse('/ai/collaboration/summarize-document', { latex_code: summarizeDocInput }, setSummarizeDocResult, setSummarizeDocLoading, setSummarizeDocError)} disabled={summarizeDocLoading || !summarizeDocInput.trim()} className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm">
                {summarizeDocLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Book className="w-4 h-4" />}
                {summarizeDocLoading ? 'Summarizing...' : 'Summarize Document'}
              </button>
              {summarizeDocError && <p className="text-red-500 text-sm mt-2">{summarizeDocError}</p>}
              {summarizeDocResult && <LatexResult content={summarizeDocResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>
          </>
        )}
      </div>
    </div>
  );
};