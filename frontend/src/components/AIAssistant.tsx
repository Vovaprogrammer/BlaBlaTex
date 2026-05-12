import React, { useState, useEffect } from 'react';
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

export const AIAssistant: React.FC<AIAssistantProps> = ({ onInsertCode }) => {
  const [activeTab, setActiveTab] = useState<'generate' | 'explain' | 'math' | 'figures' | 'references' | 'accessibility' | 'collaboration'>('generate');
  const [selectedModel, setSelectedModel] = useState('gemma4-e4b');
  const [availableModels, setAvailableModels] = useState<string[]>([]);

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

  const [mathPhysicsInput, setMathPhysicsInput] = useState('');
  const [mathPhysicsResult, setMathPhysicsResult] = useState('');
  const [mathPhysicsLoading, setMathPhysicsLoading] = useState(false);
  const [mathPhysicsError, setMathPhysicsError] = useState('');

  const [mathCheckInput, setMathCheckInput] = useState('');
  const [mathCheckResult, setMathCheckResult] = useState('');
  const [mathCheckLoading, setMathCheckLoading] = useState(false);
  const [mathCheckError, setMathCheckError] = useState('');

  const [copied, setCopied] = useState('');

  useEffect(() => {
    const fetchModels = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/ai/models`);
        if (response.ok) {
          const data = await response.json();
          setAvailableModels(data.models);
        }
      } catch (error) {
        console.error('Failed to fetch models:', error);
      }
    };
    fetchModels();
  }, []);

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
              body: JSON.stringify({ ...body, model: selectedModel }),
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
                              setResult(accumulatedText);
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
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">AI Assistant</h2>
          <div className="flex items-center gap-2">
            <Settings className="w-4 h-4 text-gray-400" />
            <span className="text-xs text-gray-500 dark:text-gray-400 font-medium px-2 py-1 bg-gray-100 dark:bg-gray-700 rounded-lg">
              Powered by Gemma 4 E4B
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-1">
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

      <div className="flex-1 p-4 overflow-y-auto space-y-6">
        {activeTab === 'generate' && (
          <>
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
              {documentResult && (
                <div className="mt-3 relative">
                  <pre className="p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md text-sm whitespace-pre-wrap break-words max-h-48 overflow-auto">{documentResult}</pre>
                  <div className="flex gap-2 mt-2">
                    <button onClick={() => copyToClipboard(documentResult)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                      {copied === documentResult ? <CheckCircle className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
                      {copied === documentResult ? 'Copied!' : 'Copy'}
                    </button>
                    <button onClick={() => onInsertCode(documentResult)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors">
                      <Send className="w-4 h-4" />
                      Insert
                    </button>
                  </div>
                </div>
              )}
            </div>

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
              {formulaResult && (
                <div className="mt-3 relative">
                  <pre className="p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md text-sm whitespace-pre-wrap break-words max-h-48 overflow-auto">{formulaResult}</pre>
                  <div className="flex gap-2 mt-2">
                    <button onClick={() => copyToClipboard(formulaResult)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                      {copied === formulaResult ? <CheckCircle className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
                      {copied === formulaResult ? 'Copied!' : 'Copy'}
                    </button>
                    <button onClick={() => onInsertCode(formulaResult)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors">
                      <Send className="w-4 h-4" />
                      Insert
                    </button>
                  </div>
                </div>
              )}
            </div>

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
              {partResult && (
                <div className="mt-3 relative">
                  <pre className="p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md text-sm whitespace-pre-wrap break-words max-h-48 overflow-auto">{partResult}</pre>
                  <div className="flex gap-2 mt-2">
                    <button onClick={() => copyToClipboard(partResult)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                      {copied === partResult ? <CheckCircle className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
                      {copied === partResult ? 'Copied!' : 'Copy'}
                    </button>
                    <button onClick={() => onInsertCode(partResult)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors">
                      <Send className="w-4 h-4" />
                      Insert
                    </button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}

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
              {codeExplainResult && (
                <div className="mt-3 relative">
                  <pre className="p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md text-sm whitespace-pre-wrap break-words max-h-48 overflow-auto">{codeExplainResult}</pre>
                  <div className="flex gap-2 mt-2">
                    <button onClick={() => copyToClipboard(codeExplainResult)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                      {copied === codeExplainResult ? <CheckCircle className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
                      {copied === codeExplainResult ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                </div>
              )}
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
              {latexExplainResult && (
                <div className="mt-3 relative">
                  <pre className="p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md text-sm whitespace-pre-wrap break-words max-h-48 overflow-auto">{latexExplainResult}</pre>
                  <div className="flex gap-2 mt-2">
                    <button onClick={() => copyToClipboard(latexExplainResult)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                      {copied === latexExplainResult ? <CheckCircle className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
                      {copied === latexExplainResult ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
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
              {mathSolveResult && (
                <div className="mt-3 relative">
                  <pre className="p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md text-sm whitespace-pre-wrap break-words max-h-48 overflow-auto">{mathSolveResult}</pre>
                  <button onClick={() => copyToClipboard(mathSolveResult)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors mt-2">
                    <Copy className="w-4 h-4" /> Copy
                  </button>
                </div>
              )}
            </div>

            {/* Derive/Integrate */}
            <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2 flex items-center gap-2">
                <Sigma className="w-4 h-4" />
                Derive / Integrate
              </h3>
              <textarea
                value={mathDeriveInput}
                onChange={(e) => setMathDeriveInput(e.target.value)}
                placeholder="E.g., x^3 + 2x^2 + 5x"
                className="w-full h-16 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent text-sm"
              />
              <button
                onClick={() => handleStreamResponse('/ai/math/derive', { expression: mathDeriveInput }, setMathDeriveResult, setMathDeriveLoading, setMathDeriveError)}
                disabled={mathDeriveLoading || !mathDeriveInput.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors text-sm"
              >
                {mathDeriveLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sigma className="w-4 h-4" />}
                {mathDeriveLoading ? 'Calculating...' : 'Derive'}
              </button>
              {mathDeriveError && <p className="text-red-500 text-sm mt-2">{mathDeriveError}</p>}
              {mathDeriveResult && (
                <div className="mt-3 relative">
                  <pre className="p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md text-sm whitespace-pre-wrap break-words max-h-48 overflow-auto">{mathDeriveResult}</pre>
                  <button onClick={() => copyToClipboard(mathDeriveResult)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors mt-2">
                    <Copy className="w-4 h-4" /> Copy
                  </button>
                </div>
              )}
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
              {mathPhysicsResult && (
                <div className="mt-3 relative">
                  <pre className="p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md text-sm whitespace-pre-wrap break-words max-h-48 overflow-auto">{mathPhysicsResult}</pre>
                  <button onClick={() => copyToClipboard(mathPhysicsResult)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors mt-2">
                    <Copy className="w-4 h-4" /> Copy
                  </button>
                </div>
              )}
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
              {mathCheckResult && (
                <div className="mt-3 relative">
                  <pre className="p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md text-sm whitespace-pre-wrap break-words max-h-48 overflow-auto">{mathCheckResult}</pre>
                  <button onClick={() => copyToClipboard(mathCheckResult)} className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors mt-2">
                    <Copy className="w-4 h-4" /> Copy
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};