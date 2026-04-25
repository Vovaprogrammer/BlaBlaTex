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
  Settings
} from 'lucide-react';
import { apiService } from '../services/api';

const API_BASE_URL = 'http://localhost:8000';

type ApiService = {
  generateLatex: (prompt: string, model?: string) => Promise<{ code: string }>;
  explainLatex: (code: string, model?: string) => Promise<{ explanation: string }>;
  deriveEquation: (expr: string) => Promise<{ steps: string[]; final_result: string }>;
  checkUnits: (expr: string) => Promise<{ consistent: boolean; details: string }>;
  verifyEquation: (lhs: string, rhs: string) => Promise<{ equivalent: boolean; simplified_lhs: string; simplified_rhs: string }>;
  generateTable: (data: { csv: string; has_header: boolean; use_booktabs: boolean }) => Promise<{ latex: string }>;
  generateDiagram: (data: { prompt: string; strict_latex_only: boolean }) => Promise<{ latex: string }>;
  fetchBibtex: (id: string) => Promise<{ bibtex: string }>;
  addAltText: (code: string) => Promise<{ alt_text: string }>;
  checkColor: (colors: string[]) => Promise<{ compliant: boolean; issues: string[] }>;
  checkTemplate: (code: string) => Promise<{ compliant: boolean; issues: string[] }>;
  getDiff: (oldText: string, newText: string) => Promise<{ diff: string }>;
  summarizeChanges: (oldText: string, newText: string) => Promise<{ summary: string }>;
};

interface AIAssistantProps {
  onInsertCode: (code: string) => void;
}

export const AIAssistant: React.FC<AIAssistantProps> = ({ onInsertCode }) => {
  const api = apiService as unknown as ApiService;
  const [activeTab, setActiveTab] = useState<'generate' | 'explain' | 'math' | 'figures' | 'references' | 'accessibility' | 'collaboration'>('generate');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [copied, setCopied] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [selectedModel, setSelectedModel] = useState('gemma4-e4b');
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [streamingText, setStreamingText] = useState<string>('');

  // Form states
  const [prompt, setPrompt] = useState('');
  const [codeToExplain, setCodeToExplain] = useState('');
  const [mathExpression, setMathExpression] = useState('');
  const [unitsExpression, setUnitsExpression] = useState('');
  const [lhs, setLhs] = useState('');
  const [rhs, setRhs] = useState('');
  const [csvData, setCsvData] = useState('');
  const [diagramPrompt, setDiagramPrompt] = useState('');
  const [bibtexId, setBibtexId] = useState('');
  const [figureCode, setFigureCode] = useState('');
  const [colors, setColors] = useState('');
  const [templateCode, setTemplateCode] = useState('');
  const [oldText, setOldText] = useState('');
  const [newText, setNewText] = useState('');

  // Загрузка доступных моделей
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

  const clearStates = () => {
    setResult('');
    setError('');
    setCopied(false);
    setIsDownloading(false);
    setStreamingText('');
  };

  const handleGenerateStream = async () => {
    if (!prompt.trim()) return;
    
    setLoading(true);
    setResult('');
    setError('');
    setStreamingText('');
    
    try {
      const response = await fetch(`${API_BASE_URL}/ai/generate-stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: prompt, model: selectedModel })
      });
      
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let accumulatedText = '';
      
      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value);
        const lines = chunk.split('\n');
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.token) {
                accumulatedText += data.token;
                setResult(accumulatedText);
                setStreamingText(accumulatedText);
              }
              if (data.done) {
                break;
              }
            } catch (e) {
              // ignore parse errors
            }
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Generation failed');
    } finally {
      setLoading(false);
      setStreamingText('');
    }
  };

  const handleGenerate = async () => {
    if (!prompt.trim()) return;
    
    setLoading(true);
    clearStates();
    
    try {
      const response = await fetch(`${API_BASE_URL}/ai/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description: prompt, model: selectedModel })
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        if (errorData.detail && errorData.detail.includes('download')) {
          setIsDownloading(true);
        }
        throw new Error(errorData.detail || 'Generation failed');
      }
      
      const data = await response.json();
      setResult(data.code);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate LaTeX');
    } finally {
      setLoading(false);
      setIsDownloading(false);
    }
  };

  const handleExplain = async () => {
    if (!codeToExplain.trim()) return;
    
    setLoading(true);
    clearStates();
    
    try {
      const response = await fetch(`${API_BASE_URL}/ai/explain`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: codeToExplain, model: selectedModel })
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Explanation failed');
      }
      
      const data = await response.json();
      setResult(data.text || data.explanation);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to explain LaTeX');
    } finally {
      setLoading(false);
    }
  };

  const handleDeriveEquation = async () => {
    if (!mathExpression.trim()) return;
    
    setLoading(true);
    clearStates();
    
    try {
      const response = await api.deriveEquation(mathExpression);
      const resultText = `Steps:\n${response.steps.join('\n')}\n\nFinal Result: ${response.final_result}`;
      setResult(resultText);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to derive equation');
    } finally {
      setLoading(false);
    }
  };

  const handleCheckUnits = async () => {
    if (!unitsExpression.trim()) return;
    
    setLoading(true);
    clearStates();
    
    try {
      const response = await api.checkUnits(unitsExpression);
      const resultText = `Units Consistent: ${response.consistent ? 'Yes' : 'No'}\nDetails: ${response.details}`;
      setResult(resultText);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to check units');
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyEquation = async () => {
    if (!lhs.trim() || !rhs.trim()) return;
    
    setLoading(true);
    clearStates();
    
    try {
      const response = await api.verifyEquation(lhs, rhs);
      const resultText = `Equivalent: ${response.equivalent ? 'Yes' : 'No'}\nSimplified LHS: ${response.simplified_lhs}\nSimplified RHS: ${response.simplified_rhs}`;
      setResult(resultText);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to verify equation');
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateTable = async () => {
    if (!csvData.trim()) return;
    
    setLoading(true);
    clearStates();
    
    try {
      const response = await api.generateTable({
        csv: csvData,
        has_header: true,
        use_booktabs: true,
      });
      setResult(response.latex);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate table');
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateDiagram = async () => {
    if (!diagramPrompt.trim()) return;
    
    setLoading(true);
    clearStates();
    
    try {
      const response = await api.generateDiagram({
        prompt: diagramPrompt,
        strict_latex_only: true,
      });
      setResult(response.latex);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate diagram');
    } finally {
      setLoading(false);
    }
  };

  const handleFetchBibtex = async () => {
    if (!bibtexId.trim()) return;
    
    setLoading(true);
    clearStates();
    
    try {
      const response = await api.fetchBibtex(bibtexId);
      setResult(response.bibtex);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch BibTeX');
    } finally {
      setLoading(false);
    }
  };

  const handleAddAltText = async () => {
    if (!figureCode.trim()) return;
    
    setLoading(true);
    clearStates();
    
    try {
      const response = await api.addAltText(figureCode);
      setResult(response.alt_text);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate alt text');
    } finally {
      setLoading(false);
    }
  };

  const handleCheckColor = async () => {
    if (!colors.trim()) return;
    
    setLoading(true);
    clearStates();
    
    try {
      const colorArray = colors.split(',').map(c => c.trim()).filter(c => c);
      const response = await api.checkColor(colorArray);
      const resultText = `Color Compliant: ${response.compliant ? 'Yes' : 'No'}\nIssues: ${response.issues.join(', ') || 'None'}`;
      setResult(resultText);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to check colors');
    } finally {
      setLoading(false);
    }
  };

  const handleCheckTemplate = async () => {
    if (!templateCode.trim()) return;
    
    setLoading(true);
    clearStates();
    
    try {
      const response = await api.checkTemplate(templateCode);
      const resultText = `Template Compliant: ${response.compliant ? 'Yes' : 'No'}\nIssues: ${response.issues.join(', ') || 'None'}`;
      setResult(resultText);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to check template');
    } finally {
      setLoading(false);
    }
  };

  const handleGetDiff = async () => {
    if (!oldText.trim() || !newText.trim()) return;
    
    setLoading(true);
    clearStates();
    
    try {
      const response = await api.getDiff(oldText, newText);
      setResult(response.diff);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate diff');
    } finally {
      setLoading(false);
    }
  };

  const handleSummarizeChanges = async () => {
    if (!oldText.trim() || !newText.trim()) return;
    
    setLoading(true);
    clearStates();
    
    try {
      const response = await api.summarizeChanges(oldText, newText);
      setResult(response.summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to summarize changes');
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(result);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  const insertCode = () => {
    onInsertCode(result);
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
              onClick={() => {
                setActiveTab(id);
                clearStates();
              }}
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

      <div className="flex-1 p-4 overflow-y-auto">
        {activeTab === 'generate' && (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                Describe what you want to generate
              </label>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="E.g., Create a mathematical proof for the Pythagorean theorem..."
                className="w-full h-40 p-3 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent"
              />
            </div>
            <button
              onClick={handleGenerateStream}
              disabled={loading || !prompt.trim()}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}
              {loading ? (isDownloading ? 'Downloading model...' : 'Generating...') : 'Generate LaTeX'}
            </button>
            
            {/* Индикатор "печатает..." */}
            {loading && streamingText && (
              <div className="flex items-center gap-2 text-gray-500 dark:text-gray-400 text-sm">
                <Loader2 className="w-3 h-3 animate-spin" />
                <span>AI is typing... {streamingText.length > 0 ? `(${streamingText.length} chars)` : ''}</span>
              </div>
            )}
          </div>
        )}

        {activeTab === 'explain' && (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                LaTeX code to explain
              </label>
              <textarea
                value={codeToExplain}
                onChange={(e) => setCodeToExplain(e.target.value)}
                placeholder="Paste your LaTeX code here..."
                className="w-full h-24 p-3 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 rounded-md focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent"
              />
            </div>
            <button
              onClick={handleExplain}
              disabled={loading || !codeToExplain.trim()}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <HelpCircle className="w-4 h-4" />}
              Explain Code
            </button>
          </div>
        )}

        {activeTab === 'math' && (
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Derive Equation</h3>
              <input
                type="text"
                value={mathExpression}
                onChange={(e) => setMathExpression(e.target.value)}
                placeholder="e.g., x^2 + 2x + 1"
                className="w-full p-3 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-white rounded-md focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent"
              />
              <button
                onClick={handleDeriveEquation}
                disabled={loading || !mathExpression.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <TrendingUp className="w-4 h-4" />}
                Derive
              </button>
            </div>

            <div className="border-t pt-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Check Units</h3>
              <input
                type="text"
                value={unitsExpression}
                onChange={(e) => setUnitsExpression(e.target.value)}
                placeholder="e.g., F = ma (force = mass * acceleration)"
                className="w-full p-3 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-white rounded-md focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent"
              />
              <button
                onClick={handleCheckUnits}
                disabled={loading || !unitsExpression.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-yellow-600 text-white rounded-md hover:bg-yellow-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Shield className="w-4 h-4" />}
                Check Units
              </button>
            </div>

            <div className="border-t pt-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Verify Equation</h3>
              <div className="space-y-2">
                <input
                  type="text"
                  value={lhs}
                  onChange={(e) => setLhs(e.target.value)}
                  placeholder="Left-hand side"
                  className="w-full p-3 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-white rounded-md focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent"
                />
                <input
                  type="text"
                  value={rhs}
                  onChange={(e) => setRhs(e.target.value)}
                  placeholder="Right-hand side"
                  className="w-full p-3 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-white rounded-md focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent"
                />
              </div>
              <button
                onClick={handleVerifyEquation}
                disabled={loading || !lhs.trim() || !rhs.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-orange-600 text-white rounded-md hover:bg-orange-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
                Verify
              </button>
            </div>
          </div>
        )}

        {activeTab === 'figures' && (
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Generate Table</h3>
              <textarea
                value={csvData}
                onChange={(e) => setCsvData(e.target.value)}
                placeholder="Name,Age,Score&#10;Alice,25,95&#10;Bob,30,87"
                className="w-full h-20 p-3 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 rounded-md focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent font-mono text-sm"
              />
              <button
                onClick={handleGenerateTable}
                disabled={loading || !csvData.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Table className="w-4 h-4" />}
                Generate Table
              </button>
            </div>

            <div className="border-t pt-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Generate Diagram</h3>
              <textarea
                value={diagramPrompt}
                onChange={(e) => setDiagramPrompt(e.target.value)}
                placeholder="Describe the diagram you want to create..."
                className="w-full h-20 p-3 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 rounded-md focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent"
              />
              <button
                onClick={handleGenerateDiagram}
                disabled={loading || !diagramPrompt.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-teal-600 text-white rounded-md hover:bg-teal-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Palette className="w-4 h-4" />}
                Generate Diagram
              </button>
            </div>
          </div>
        )}

        {activeTab === 'references' && (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                DOI, arXiv ID, or other identifier
              </label>
              <input
                type="text"
                value={bibtexId}
                onChange={(e) => setBibtexId(e.target.value)}
                placeholder="e.g., 10.1234/example or arXiv:2101.00001"
                className="w-full p-3 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-white rounded-md focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent"
              />
              <button
                onClick={handleFetchBibtex}
                disabled={loading || !bibtexId.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-cyan-600 text-white rounded-md hover:bg-cyan-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Book className="w-4 h-4" />}
                Fetch BibTeX
              </button>
            </div>
          </div>
        )}

        {activeTab === 'accessibility' && (
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Generate Alt Text</h3>
              <textarea
                value={figureCode}
                onChange={(e) => setFigureCode(e.target.value)}
                placeholder="Paste your figure LaTeX code here..."
                className="w-full h-20 p-3 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 rounded-md focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent font-mono text-sm"
              />
              <button
                onClick={handleAddAltText}
                disabled={loading || !figureCode.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Shield className="w-4 h-4" />}
                Generate Alt Text
              </button>
            </div>

            <div className="border-t pt-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Check Colors</h3>
              <input
                type="text"
                value={colors}
                onChange={(e) => setColors(e.target.value)}
                placeholder="e.g., #FF0000, #00FF00, #0000FF"
                className="w-full p-3 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-white rounded-md focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent"
              />
              <button
                onClick={handleCheckColor}
                disabled={loading || !colors.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Palette className="w-4 h-4" />}
                Check Colors
              </button>
            </div>

            <div className="border-t pt-4">
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Check Template Compliance</h3>
              <textarea
                value={templateCode}
                onChange={(e) => setTemplateCode(e.target.value)}
                placeholder="Paste your LaTeX document here..."
                className="w-full h-20 p-3 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 rounded-md focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent font-mono text-sm"
              />
              <button
                onClick={handleCheckTemplate}
                disabled={loading || !templateCode.trim()}
                className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
                Check Template
              </button>
            </div>
          </div>
        )}

        {activeTab === 'collaboration' && (
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">Generate Diff</h3>
              <textarea
                value={oldText}
                onChange={(e) => setOldText(e.target.value)}
                placeholder="Original text..."
                className="w-full h-16 p-3 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 rounded-md focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent font-mono text-sm mb-2"
              />
              <textarea
                value={newText}
                onChange={(e) => setNewText(e.target.value)}
                placeholder="Modified text..."
                className="w-full h-16 p-3 border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-black dark:text-white placeholder-gray-400 dark:placeholder-gray-500 rounded-md focus:ring-2 focus:ring-blue-500 dark:focus:border-blue-400 focus:border-transparent font-mono text-sm"
              />
              <div className="flex gap-2 mt-2">
                <button
                  onClick={handleGetDiff}
                  disabled={loading || !oldText.trim() || !newText.trim()}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                >
                  {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Users className="w-4 h-4" />}
                  Get Diff
                </button>
                <button
                  onClick={handleSummarizeChanges}
                  disabled={loading || !oldText.trim() || !newText.trim()}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                >
                  {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <TrendingUp className="w-4 h-4" />}
                  Summarize
                </button>
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="mt-4 p-3 text-red-800 dark:text-red-300 border border-red-200 dark:border-red-800 rounded-md">
            <div className="flex items-center gap-2 text-red-800">
              <AlertCircle className="w-4 h-4" />
              <span className="text-sm font-medium">Error</span>
            </div>
            <p className="text-sm text-red-700 mt-1">{error}</p>
          </div>
        )}

        {result && (
          <div className="mt-4 space-y-3">
            <div className="flex items-center gap-2">
              <CheckCircle className="w-4 h-4 text-green-600" />
              <span className="text-sm font-medium text-green-800 dark:text-green-300">Result</span>
            </div>
            
            <div className="relative">
              <pre className="p-3 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-gray-100 rounded-md text-sm whitespace-pre-wrap max-h-64 overflow-auto">
                {result}
              </pre>
              
              <div className="flex gap-2 mt-2">
                <button
                  onClick={copyToClipboard}
                  className="flex items-center gap-1 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  {copied ? <CheckCircle className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
                  {copied ? 'Copied!' : 'Copy'}
                </button>
                
                {activeTab !== 'explain' && (
                  <button
                    onClick={insertCode}
                    className="flex items-center gap-1 px-3 py-1.5 text-sm text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors"
                  >
                    <Send className="w-4 h-4" />
                    Insert
                  </button>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};