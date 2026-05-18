import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import {
  Wand2, HelpCircle, Calculator, Table, BarChart3, Palette, Book,
  Send, Loader2, Copy, CheckCircle, Shield, Users, Settings,
  FileText, Sigma, Puzzle, TrendingUp, ChevronDown
} from 'lucide-react';

const API_BASE_URL = 'http://localhost:8000';

interface AIAssistantProps {
  onInsertCode: (code: string) => void;
}

const MarkdownRenderer: React.FC<{ content: string }> = ({ content }) => (
  <div className="prose prose-sm dark:prose-invert max-w-none">
    <ReactMarkdown
      remarkPlugins={[remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        code({ className, children, ...props }: any) {
          const match = /language-(\w+)/.exec(className || '');
          const isInline = !match && !className;
          if (isInline) {
            return <code className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-800 rounded text-sm font-mono text-pink-600 dark:text-pink-400" {...props}>{children}</code>;
          }
          return <pre className="p-3 bg-gray-100 dark:bg-gray-800 rounded-md overflow-x-auto my-2 border border-gray-200 dark:border-gray-700"><code className={`text-sm font-mono ${match ? `language-${match[1]}` : ''}`}>{children}</code></pre>;
        },
        p: ({ children }: any) => <p className="mb-2 last:mb-0 leading-relaxed text-gray-800 dark:text-gray-200">{children}</p>,
        ul: ({ children }: any) => <ul className="list-disc pl-5 mb-2 space-y-1">{children}</ul>,
        ol: ({ children }: any) => <ol className="list-decimal pl-5 mb-2 space-y-1">{children}</ol>,
        li: ({ children }: any) => <li className="text-gray-700 dark:text-gray-300">{children}</li>,
        h3: ({ children }: any) => <h3 className="text-base font-semibold mt-3 mb-1 text-gray-800 dark:text-gray-200">{children}</h3>,
        strong: ({ children }: any) => <strong className="font-semibold text-gray-900 dark:text-white">{children}</strong>,
        em: ({ children }: any) => <em className="italic text-gray-700 dark:text-gray-300">{children}</em>,
      }}
    >
      {content}
    </ReactMarkdown>
  </div>
);

const LatexResult: React.FC<{ content: string; onInsert: (code: string) => void; copied: string; onCopy: (text: string) => void }> = ({ content, onInsert, copied, onCopy }) => (
  <div className="mt-3 relative max-w-full animate-fade-in">
    <pre className="p-3 bg-gradient-to-b from-white to-gray-50 dark:from-gray-800 dark:to-gray-700 border border-gray-200 dark:border-gray-700 rounded-md text-sm font-mono whitespace-pre-wrap break-all max-h-96 overflow-auto leading-relaxed max-w-full">{content}</pre>
    <div className="flex gap-2 mt-2">
      <button onClick={() => onCopy(content)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
        {copied === content ? <CheckCircle className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
        {copied === content ? 'Copied!' : 'Copy'}
      </button>
      <button onClick={() => onInsert(content)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors shadow-md">
        <Send className="w-4 h-4" /> Insert
      </button>
    </div>
  </div>
);

const MarkdownResult: React.FC<{ content: string; copied: string; onCopy: (text: string) => void }> = ({ content, copied, onCopy }) => (
  <div className="mt-3 relative max-w-full animate-fade-in">
    <div className="max-h-96 overflow-auto max-w-full"><MarkdownRenderer content={content} /></div>
    <button onClick={() => onCopy(content)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors mt-2">
      {copied === content ? <CheckCircle className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
      {copied === content ? 'Copied!' : 'Copy'}
    </button>
  </div>
);

const PlainTextResult: React.FC<{ content: string; copied: string; onCopy: (text: string) => void }> = ({ content, copied, onCopy }) => (
  <div className="mt-3 relative max-w-full animate-fade-in">
    <pre className="p-3 bg-gradient-to-b from-white to-gray-50 dark:from-gray-800 dark:to-gray-700 border border-gray-200 dark:border-gray-700 rounded-md text-sm whitespace-pre-wrap break-words max-h-96 overflow-auto leading-relaxed max-w-full">{content}</pre>
    <button onClick={() => onCopy(content)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors mt-2">
      {copied === content ? <CheckCircle className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
      {copied === content ? 'Copied!' : 'Copy'}
    </button>
  </div>
);

// Styled dropdown (like LaTeXEditor compiler selector)
const Dropdown: React.FC<{ value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }> = ({ value, onChange, options }) => {
  const [open, setOpen] = useState(false);
  const label = options.find(o => o.value === value)?.label || value;
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 shadow-sm transition-colors">
        {label}
        <ChevronDown className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 mt-1 w-48 bg-white dark:bg-gray-800 rounded-lg shadow-xl z-20 border border-gray-200 dark:border-gray-600 overflow-hidden">
            {options.map(opt => (
              <button key={opt.value} className={`w-full px-4 py-2 text-left text-sm hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors ${opt.value === value ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 font-medium' : 'text-gray-700 dark:text-gray-300'}`}
                onClick={() => { onChange(opt.value); setOpen(false); }}>
                {opt.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

export const AIAssistant: React.FC<AIAssistantProps> = ({ onInsertCode }) => {
  const [activeTab, setActiveTab] = useState<'generate' | 'explain' | 'math' | 'figures' | 'references' | 'accessibility' | 'collaboration'>('generate');

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

  const [codeToExplain, setCodeToExplain] = useState('');
  const [codeExplainResult, setCodeExplainResult] = useState('');
  const [codeExplainLoading, setCodeExplainLoading] = useState(false);
  const [codeExplainError, setCodeExplainError] = useState('');

  const [latexQuestion, setLatexQuestion] = useState('');
  const [latexExplainResult, setLatexExplainResult] = useState('');
  const [latexExplainLoading, setLatexExplainLoading] = useState(false);
  const [latexExplainError, setLatexExplainError] = useState('');

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
      url: string, body: any, setResult: (val: string) => void,
      setLoading: (val: boolean) => void, setError: (val: string) => void
  ) => {
      setLoading(true); setError(''); setResult('');
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 300000);
      try {
          const response = await fetch(`${API_BASE_URL}${url}`, {
              method: 'POST', headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
              body: JSON.stringify(body), signal: controller.signal
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          if (!response.body) throw new Error('No response body');
          const reader = response.body.getReader();
          const decoder = new TextDecoder('utf-8');
          let accumulatedText = '', buffer = '';
          while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              buffer += decoder.decode(value, { stream: true });
              const events = buffer.split('\n\n'); buffer = events.pop() || '';
              for (const event of events) {
                  const lines = event.split('\n');
                  for (const line of lines) {
                      if (!line.startsWith('data: ')) continue;
                      try {
                          const data = JSON.parse(line.slice(6));
                          if (data.error) { setError(data.error); continue; }
                          if (data.token !== undefined) {
                              accumulatedText += data.token;
                              setResult(accumulatedText.replace(/(?<!\\)\\\[/g, '$$').replace(/(?<!\\)\\\]/g, '$$').replace(/(?<!\\)\\\(/g, '$').replace(/(?<!\\)\\\)/g, '$'));
                          }
                          if (data.done) { setLoading(false); return; }
                      } catch (err) { console.error('JSON parse error:', err); }
                  }
              }
          }
      } catch (err: any) {
          setError(err.name === 'AbortError' ? 'Request timed out' : err.message || 'Request failed');
      } finally { clearTimeout(timeoutId); setLoading(false); }
  };

  const copyToClipboard = async (text: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(text); setTimeout(() => setCopied(''), 2000); } catch (err) {}
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

  const tabColors: Record<string, string> = {
    generate: 'border-l-blue-500',
    explain: 'border-l-green-500',
    math: 'border-l-purple-500',
    figures: 'border-l-orange-500',
    references: 'border-l-cyan-500',
    accessibility: 'border-l-emerald-500',
    collaboration: 'border-l-rose-500',
  };

  const cardClass = (tab: string) => `border border-gray-200 dark:border-gray-700 rounded-lg p-4 border-l-4 ${tabColors[tab] || ''} bg-white dark:bg-gray-800`;

  const inputClass = "w-full p-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 focus:border-blue-400 outline-none text-sm";
  const btnClass = (color: string) => `w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 ${color} text-white rounded-lg hover:opacity-90 disabled:bg-gray-400 disabled:text-gray-600 disabled:cursor-not-allowed transition-all text-sm shadow-md`;

  return (
    <div className="flex flex-col h-full bg-gradient-to-br from-slate-300 via-blue-300 to-indigo-300 dark:from-slate-950 dark:via-indigo-950 dark:to-blue-950 border-l border-gray-200 dark:border-gray-700 max-w-full overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-2">AI Assistant</h2>
        <div className="flex items-center gap-2 mb-3">
          <Settings className="w-4 h-4 text-gray-400" />
          <span className="text-xs text-gray-500 dark:text-gray-400 font-medium px-2 py-1 bg-gray-100 dark:bg-gray-700 rounded-lg">
            Powered by Llama 3.1 8B + Qwen 80B
          </span>
        </div>
        <div className="flex flex-wrap gap-1">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button key={id} onClick={() => setActiveTab(id)} className={`relative flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${activeTab === id ? 'bg-blue-500 text-white shadow-md dark:bg-blue-900/40 dark:text-blue-300' : 'text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800'}`}>
              <Icon className="w-4 h-4" /> {label}
              {activeTab === id && <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-6 h-0.5 bg-white dark:bg-blue-400 rounded-full"></span>}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 p-4 overflow-y-auto space-y-6">
        {/* GENERATE TAB */}
        {activeTab === 'generate' && (
          <>
            <div className={cardClass('generate')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><FileText className="w-4 h-4" />Generate Full Document</h3>
              <textarea value={documentPrompt} onChange={(e) => setDocumentPrompt(e.target.value)} placeholder="E.g., Create an article about Newton's laws..." className={`${inputClass} h-24`} />
              <button onClick={() => handleStreamResponse('/ai/generate/document', { description: documentPrompt }, setDocumentResult, setDocumentLoading, setDocumentError)} disabled={documentLoading || !documentPrompt.trim()} className={btnClass('bg-blue-600 hover:bg-blue-700')}>
                {documentLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}{documentLoading ? 'Generating...' : 'Generate Document'}
              </button>
              {documentError && <p className="text-red-500 text-sm mt-2">{documentError}</p>}
              {documentResult && <LatexResult content={documentResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('generate')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Sigma className="w-4 h-4" />Generate Formula</h3>
              <textarea value={formulaPrompt} onChange={(e) => setFormulaPrompt(e.target.value)} placeholder="E.g., Einstein's mass-energy equivalence..." className={`${inputClass} h-20`} />
              <button onClick={() => handleStreamResponse('/ai/generate/formula', { description: formulaPrompt }, setFormulaResult, setFormulaLoading, setFormulaError)} disabled={formulaLoading || !formulaPrompt.trim()} className={btnClass('bg-purple-600 hover:bg-purple-700')}>
                {formulaLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sigma className="w-4 h-4" />}{formulaLoading ? 'Generating...' : 'Generate Formula'}
              </button>
              {formulaError && <p className="text-red-500 text-sm mt-2">{formulaError}</p>}
              {formulaResult && <LatexResult content={formulaResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('generate')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Puzzle className="w-4 h-4" />Generate Part</h3>
              <div className="flex gap-2 mb-2">
                <Dropdown value={partType} onChange={setPartType} options={[
                  { value: 'section', label: 'Section' }, { value: 'theorem', label: 'Theorem' }, { value: 'proof', label: 'Proof' }, { value: 'definition', label: 'Definition' }, { value: 'example', label: 'Example' }
                ]} />
              </div>
              <textarea value={partPrompt} onChange={(e) => setPartPrompt(e.target.value)} placeholder="E.g., Explain the concept of limits in calculus..." className={`${inputClass} h-20`} />
              <button onClick={() => handleStreamResponse('/ai/generate/part', { description: partPrompt, part_type: partType }, setPartResult, setPartLoading, setPartError)} disabled={partLoading || !partPrompt.trim()} className={btnClass('bg-teal-600 hover:bg-teal-700')}>
                {partLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Puzzle className="w-4 h-4" />}{partLoading ? 'Generating...' : `Generate ${partType}`}
              </button>
              {partError && <p className="text-red-500 text-sm mt-2">{partError}</p>}
              {partResult && <LatexResult content={partResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>
          </>
        )}

        {/* EXPLAIN TAB */}
        {activeTab === 'explain' && (
          <>
            <div className={cardClass('explain')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><FileText className="w-4 h-4" />Explain Code</h3>
              <textarea value={codeToExplain} onChange={(e) => setCodeToExplain(e.target.value)} placeholder="Paste your LaTeX code here..." className={`${inputClass} h-24`} />
              <button onClick={() => handleStreamResponse('/ai/explain/code', { code: codeToExplain }, setCodeExplainResult, setCodeExplainLoading, setCodeExplainError)} disabled={codeExplainLoading || !codeToExplain.trim()} className={btnClass('bg-green-600 hover:bg-green-700')}>
                {codeExplainLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <HelpCircle className="w-4 h-4" />}{codeExplainLoading ? 'Explaining...' : 'Explain Code'}
              </button>
              {codeExplainError && <p className="text-red-500 text-sm mt-2">{codeExplainError}</p>}
              {codeExplainResult && <MarkdownResult content={codeExplainResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('explain')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><HelpCircle className="w-4 h-4" />Ask LaTeX Question</h3>
              <textarea value={latexQuestion} onChange={(e) => setLatexQuestion(e.target.value)} placeholder="E.g., How to center text in LaTeX?" className={`${inputClass} h-20`} />
              <button onClick={() => handleStreamResponse('/ai/explain/latex', { question: latexQuestion }, setLatexExplainResult, setLatexExplainLoading, setLatexExplainError)} disabled={latexExplainLoading || !latexQuestion.trim()} className={btnClass('bg-yellow-600 hover:bg-yellow-700')}>
                {latexExplainLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <HelpCircle className="w-4 h-4" />}{latexExplainLoading ? 'Asking...' : 'Ask Question'}
              </button>
              {latexExplainError && <p className="text-red-500 text-sm mt-2">{latexExplainError}</p>}
              {latexExplainResult && <MarkdownResult content={latexExplainResult} copied={copied} onCopy={copyToClipboard} />}
            </div>
          </>
        )}

        {/* MATH TAB */}
        {activeTab === 'math' && (
          <>
            <div className={cardClass('math')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><TrendingUp className="w-4 h-4" />Solve Equation</h3>
              <textarea value={mathSolveInput} onChange={(e) => setMathSolveInput(e.target.value)} placeholder="E.g., x^2 + 2x + 1 = 0" className={`${inputClass} h-16`} />
              <button onClick={() => handleStreamResponse('/ai/math/solve', { equation: mathSolveInput }, setMathSolveResult, setMathSolveLoading, setMathSolveError)} disabled={mathSolveLoading || !mathSolveInput.trim()} className={btnClass('bg-purple-600 hover:bg-purple-700')}>
                {mathSolveLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <TrendingUp className="w-4 h-4" />}{mathSolveLoading ? 'Solving...' : 'Solve'}
              </button>
              {mathSolveError && <p className="text-red-500 text-sm mt-2">{mathSolveError}</p>}
              {mathSolveResult && <MarkdownResult content={mathSolveResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('math')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Sigma className="w-4 h-4" />Calculus</h3>
              <div className="flex gap-2 mb-2">
                <Dropdown value={mathDeriveOperation} onChange={setMathDeriveOperation} options={[
                  { value: 'derive', label: 'Derive (производная)' }, { value: 'integrate', label: 'Integrate (интеграл)' }
                ]} />
              </div>
              <textarea value={mathDeriveInput} onChange={(e) => setMathDeriveInput(e.target.value)} placeholder="E.g., x^3 + 2x^2 + 5x" className={`${inputClass} h-16`} />
              <button onClick={() => handleStreamResponse('/ai/math/derive', { expression: mathDeriveInput, operation: mathDeriveOperation }, setMathDeriveResult, setMathDeriveLoading, setMathDeriveError)} disabled={mathDeriveLoading || !mathDeriveInput.trim()} className={btnClass('bg-indigo-600 hover:bg-indigo-700')}>
                {mathDeriveLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sigma className="w-4 h-4" />}{mathDeriveLoading ? 'Calculating...' : mathDeriveOperation === 'derive' ? 'Derive' : 'Integrate'}
              </button>
              {mathDeriveError && <p className="text-red-500 text-sm mt-2">{mathDeriveError}</p>}
              {mathDeriveResult && <MarkdownResult content={mathDeriveResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('math')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Calculator className="w-4 h-4" />Physics Formula</h3>
              <textarea value={mathPhysicsInput} onChange={(e) => setMathPhysicsInput(e.target.value)} placeholder="E.g., Express velocity from E = mv^2/2" className={`${inputClass} h-16`} />
              <button onClick={() => handleStreamResponse('/ai/math/physics', { description: mathPhysicsInput }, setMathPhysicsResult, setMathPhysicsLoading, setMathPhysicsError)} disabled={mathPhysicsLoading || !mathPhysicsInput.trim()} className={btnClass('bg-cyan-600 hover:bg-cyan-700')}>
                {mathPhysicsLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Calculator className="w-4 h-4" />}{mathPhysicsLoading ? 'Calculating...' : 'Solve'}
              </button>
              {mathPhysicsError && <p className="text-red-500 text-sm mt-2">{mathPhysicsError}</p>}
              {mathPhysicsResult && <MarkdownResult content={mathPhysicsResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('math')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Shield className="w-4 h-4" />Check Formula</h3>
              <textarea value={mathCheckInput} onChange={(e) => setMathCheckInput(e.target.value)} placeholder="E.g., E = mc^3" className={`${inputClass} h-16`} />
              <button onClick={() => handleStreamResponse('/ai/math/check', { formula: mathCheckInput }, setMathCheckResult, setMathCheckLoading, setMathCheckError)} disabled={mathCheckLoading || !mathCheckInput.trim()} className={btnClass('bg-orange-600 hover:bg-orange-700')}>
                {mathCheckLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Shield className="w-4 h-4" />}{mathCheckLoading ? 'Checking...' : 'Check'}
              </button>
              {mathCheckError && <p className="text-red-500 text-sm mt-2">{mathCheckError}</p>}
              {mathCheckResult && <MarkdownResult content={mathCheckResult} copied={copied} onCopy={copyToClipboard} />}
            </div>
          </>
        )}

        {/* FIGURES TAB */}
        {activeTab === 'figures' && (
          <>
            <div className={cardClass('figures')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Table className="w-4 h-4" />Generate Table</h3>
              <div className="flex gap-4 mb-2">
                <label className="flex items-center gap-1.5 text-xs text-gray-700 dark:text-gray-300 cursor-pointer select-none">
                  <input type="checkbox" checked={tableHasHeader} onChange={(e) => setTableHasHeader(e.target.checked)} className="w-3.5 h-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500" /> Header
                </label>
                <label className="flex items-center gap-1.5 text-xs text-gray-700 dark:text-gray-300 cursor-pointer select-none">
                  <input type="checkbox" checked={tableUseBooktabs} onChange={(e) => setTableUseBooktabs(e.target.checked)} className="w-3.5 h-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500" /> Booktabs
                </label>
              </div>
              <textarea value={tableInput} onChange={(e) => setTableInput(e.target.value)} placeholder="Name,Score\nAlice,95" className={`${inputClass} h-24 font-mono`} />
              <button onClick={() => handleStreamResponse('/ai/figures/table', { csv: tableInput, has_header: tableHasHeader, use_booktabs: tableUseBooktabs }, setTableResult, setTableLoading, setTableError)} disabled={tableLoading || !tableInput.trim()} className={btnClass('bg-indigo-600 hover:bg-indigo-700')}>
                {tableLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Table className="w-4 h-4" />}{tableLoading ? 'Generating...' : 'Generate Table'}
              </button>
              {tableError && <p className="text-red-500 text-sm mt-2">{tableError}</p>}
              {tableResult && <LatexResult content={tableResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('figures')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><BarChart3 className="w-4 h-4" />Generate Diagram</h3>
              <textarea value={diagramInput} onChange={(e) => setDiagramInput(e.target.value)} placeholder="Describe the diagram..." className={`${inputClass} h-24`} />
              <button onClick={() => handleStreamResponse('/ai/figures/diagram', { prompt: diagramInput }, setDiagramResult, setDiagramLoading, setDiagramError)} disabled={diagramLoading || !diagramInput.trim()} className={btnClass('bg-teal-600 hover:bg-teal-700')}>
                {diagramLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />}{diagramLoading ? 'Generating...' : 'Generate Diagram'}
              </button>
              {diagramError && <p className="text-red-500 text-sm mt-2">{diagramError}</p>}
              {diagramResult && <LatexResult content={diagramResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('figures')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><TrendingUp className="w-4 h-4" />Generate Plot</h3>
              <div className="grid grid-cols-2 gap-2 mb-2">
                <input type="text" value={plotXlabel} onChange={(e) => setPlotXlabel(e.target.value)} placeholder="X label" className={`${inputClass} !p-2`} />
                <input type="text" value={plotYlabel} onChange={(e) => setPlotYlabel(e.target.value)} placeholder="Y label" className={`${inputClass} !p-2`} />
                <input type="text" value={plotTitle} onChange={(e) => setPlotTitle(e.target.value)} placeholder="Title (optional)" className={`${inputClass} !p-2 col-span-2`} />
              </div>
              <textarea value={plotExpression} onChange={(e) => setPlotExpression(e.target.value)} placeholder="E.g., x^2" className={`${inputClass} h-20`} />
              <button onClick={() => handleStreamResponse('/ai/figures/plot', { expression: plotExpression, xlabel: plotXlabel, ylabel: plotYlabel, title: plotTitle }, setPlotResult, setPlotLoading, setPlotError)} disabled={plotLoading || !plotExpression.trim()} className={btnClass('bg-orange-600 hover:bg-orange-700')}>
                {plotLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <TrendingUp className="w-4 h-4" />}{plotLoading ? 'Generating...' : 'Generate Plot'}
              </button>
              {plotError && <p className="text-red-500 text-sm mt-2">{plotError}</p>}
              {plotResult && <LatexResult content={plotResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>
          </>
        )}

        {/* REFERENCES TAB */}
        {activeTab === 'references' && (
          <>
            <div className={cardClass('references')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Book className="w-4 h-4" />Fetch BibTeX</h3>
              <input type="text" value={refIdentifier} onChange={(e) => setRefIdentifier(e.target.value)} placeholder="e.g., 10.1000/xyz123" className={inputClass} />
              <button onClick={() => handleStreamResponse('/ai/references/fetch', { identifier: refIdentifier }, setRefResult, setRefLoading, setRefError)} disabled={refLoading || !refIdentifier.trim()} className={btnClass('bg-cyan-600 hover:bg-cyan-700')}>
                {refLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Book className="w-4 h-4" />}{refLoading ? 'Fetching...' : 'Fetch BibTeX'}
              </button>
              {refError && <p className="text-red-500 text-sm mt-2">{refError}</p>}
              {refResult && <LatexResult content={refResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('references')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Book className="w-4 h-4" />Format References</h3>
              <div className="flex gap-2 mb-2">
                <Dropdown value={formatRefStyle} onChange={setFormatRefStyle} options={[
                  { value: 'ieee', label: 'IEEE' }, { value: 'gost', label: 'ГОСТ' }, { value: 'apa', label: 'APA' }
                ]} />
              </div>
              <textarea value={formatRefInput} onChange={(e) => setFormatRefInput(e.target.value)} placeholder="Paste references..." className={`${inputClass} h-24`} />
              <button onClick={() => handleStreamResponse('/ai/references/format', { references: formatRefInput, style: formatRefStyle }, setFormatRefResult, setFormatRefLoading, setFormatRefError)} disabled={formatRefLoading || !formatRefInput.trim()} className={btnClass('bg-blue-600 hover:bg-blue-700')}>
                {formatRefLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Book className="w-4 h-4" />}{formatRefLoading ? 'Formatting...' : 'Format References'}
              </button>
              {formatRefError && <p className="text-red-500 text-sm mt-2">{formatRefError}</p>}
              {formatRefResult && <LatexResult content={formatRefResult} onInsert={onInsertCode} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('references')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><CheckCircle className="w-4 h-4" />Check Citation</h3>
              <textarea value={checkCitationInput} onChange={(e) => setCheckCitationInput(e.target.value)} placeholder="Paste BibTeX entry..." className={`${inputClass} h-24`} />
              <button onClick={() => handleStreamResponse('/ai/references/check', { citation: checkCitationInput }, setCheckCitationResult, setCheckCitationLoading, setCheckCitationError)} disabled={checkCitationLoading || !checkCitationInput.trim()} className={btnClass('bg-green-600 hover:bg-green-700')}>
                {checkCitationLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}{checkCitationLoading ? 'Checking...' : 'Check Citation'}
              </button>
              {checkCitationError && <p className="text-red-500 text-sm mt-2">{checkCitationError}</p>}
              {checkCitationResult && <MarkdownResult content={checkCitationResult} copied={copied} onCopy={copyToClipboard} />}
            </div>
          </>
        )}

        {/* ACCESSIBILITY TAB */}
        {activeTab === 'accessibility' && (
          <>
            <div className={cardClass('accessibility')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Shield className="w-4 h-4" />Generate Alt Text</h3>
              <textarea value={altTextInput} onChange={(e) => setAltTextInput(e.target.value)} placeholder="Paste figure/formula..." className={`${inputClass} h-24`} />
              <button onClick={() => handleStreamResponse('/ai/accessibility/alt-text', { figure_code: altTextInput }, setAltTextResult, setAltTextLoading, setAltTextError)} disabled={altTextLoading || !altTextInput.trim()} className={btnClass('bg-green-600 hover:bg-green-700')}>
                {altTextLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Shield className="w-4 h-4" />}{altTextLoading ? 'Generating...' : 'Generate Alt Text'}
              </button>
              {altTextError && <p className="text-red-500 text-sm mt-2">{altTextError}</p>}
              {altTextResult && <MarkdownResult content={altTextResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('accessibility')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Palette className="w-4 h-4" />Check Colors</h3>
              <div className="flex gap-2 mb-2">
                <Dropdown value={colorPalette} onChange={setColorPalette} options={[
                  { value: 'all', label: 'All types' }, { value: 'protanopia', label: 'Protanopia' }, { value: 'deuteranopia', label: 'Deuteranopia' }, { value: 'tritanopia', label: 'Tritanopia' }
                ]} />
              </div>
              <textarea value={colorInput} onChange={(e) => setColorInput(e.target.value)} placeholder="#FF0000, #00FF00" className={`${inputClass} h-20`} />
              <button onClick={() => handleStreamResponse('/ai/accessibility/check-colors', { colors: colorInput.split(',').map(c => c.trim()), palette_type: colorPalette }, setColorResult, setColorLoading, setColorError)} disabled={colorLoading || !colorInput.trim()} className={btnClass('bg-purple-600 hover:bg-purple-700')}>
                {colorLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Palette className="w-4 h-4" />}{colorLoading ? 'Checking...' : 'Check Colors'}
              </button>
              {colorError && <p className="text-red-500 text-sm mt-2">{colorError}</p>}
              {colorResult && <MarkdownResult content={colorResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('accessibility')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><CheckCircle className="w-4 h-4" />Check Template</h3>
              <div className="flex gap-2 mb-2">
                <Dropdown value={templateType} onChange={setTemplateType} options={[
                  { value: 'ieee', label: 'IEEE' }, { value: 'acm', label: 'ACM' }, { value: 'gost', label: 'ГОСТ' }
                ]} />
              </div>
              <textarea value={templateInput} onChange={(e) => setTemplateInput(e.target.value)} placeholder="Paste LaTeX document..." className={`${inputClass} h-24`} />
              <button onClick={() => handleStreamResponse('/ai/accessibility/check-template', { latex_code: templateInput, template: templateType }, setTemplateResult, setTemplateLoading, setTemplateError)} disabled={templateLoading || !templateInput.trim()} className={btnClass('bg-indigo-600 hover:bg-indigo-700')}>
                {templateLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}{templateLoading ? 'Checking...' : 'Check Template'}
              </button>
              {templateError && <p className="text-red-500 text-sm mt-2">{templateError}</p>}
              {templateResult && <MarkdownResult content={templateResult} copied={copied} onCopy={copyToClipboard} />}
            </div>
          </>
        )}

        {/* COLLABORATION TAB */}
        {activeTab === 'collaboration' && (
          <>
            <div className={cardClass('collaboration')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Users className="w-4 h-4" />Get Diff</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Compare two versions and see what changed.</p>
              <textarea value={diffOldText} onChange={(e) => setDiffOldText(e.target.value)} placeholder="Old version..." className={`${inputClass} h-24 mb-2`} />
              <textarea value={diffNewText} onChange={(e) => setDiffNewText(e.target.value)} placeholder="New version..." className={`${inputClass} h-24`} />
              <button onClick={() => handleStreamResponse('/ai/collaboration/diff', { old_text: diffOldText, new_text: diffNewText }, setDiffResult, setDiffLoading, setDiffError)} disabled={diffLoading || !diffOldText.trim() || !diffNewText.trim()} className={btnClass('bg-blue-600 hover:bg-blue-700')}>
                {diffLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Users className="w-4 h-4" />}{diffLoading ? 'Comparing...' : 'Get Diff'}
              </button>
              {diffError && <p className="text-red-500 text-sm mt-2">{diffError}</p>}
              {diffResult && <MarkdownResult content={diffResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('collaboration')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><FileText className="w-4 h-4" />Summarize Changes</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Get a human-readable summary of changes.</p>
              <textarea value={summarizeOldText} onChange={(e) => setSummarizeOldText(e.target.value)} placeholder="Old version..." className={`${inputClass} h-24 mb-2`} />
              <textarea value={summarizeNewText} onChange={(e) => setSummarizeNewText(e.target.value)} placeholder="New version..." className={`${inputClass} h-24`} />
              <button onClick={() => handleStreamResponse('/ai/collaboration/summarize', { old_text: summarizeOldText, new_text: summarizeNewText }, setSummarizeResult, setSummarizeLoading, setSummarizeError)} disabled={summarizeLoading || !summarizeOldText.trim() || !summarizeNewText.trim()} className={btnClass('bg-green-600 hover:bg-green-700')}>
                {summarizeLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}{summarizeLoading ? 'Summarizing...' : 'Summarize Changes'}
              </button>
              {summarizeError && <p className="text-red-500 text-sm mt-2">{summarizeError}</p>}
              {summarizeResult && <MarkdownResult content={summarizeResult} copied={copied} onCopy={copyToClipboard} />}
            </div>

            <div className={cardClass('collaboration')}>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2"><Book className="w-4 h-4" />Summarize Document</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">Create a concise summary of a full LaTeX document.</p>
              <textarea value={summarizeDocInput} onChange={(e) => setSummarizeDocInput(e.target.value)} placeholder="Paste your full LaTeX document..." className={`${inputClass} h-32`} />
              <button onClick={() => handleStreamResponse('/ai/collaboration/summarize-document', { latex_code: summarizeDocInput }, setSummarizeDocResult, setSummarizeDocLoading, setSummarizeDocError)} disabled={summarizeDocLoading || !summarizeDocInput.trim()} className={btnClass('bg-purple-600 hover:bg-purple-700')}>
                {summarizeDocLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Book className="w-4 h-4" />}{summarizeDocLoading ? 'Summarizing...' : 'Summarize Document'}
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