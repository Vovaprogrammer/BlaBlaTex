import React, { useState, useEffect } from 'react';
import { Download, AlertTriangle, Loader2, RefreshCw, FileText, Sparkles } from 'lucide-react';

interface PDFViewerProps {
  pdfBase64: string | null;
  errorLog: string;
  loading: boolean;
  onFixErrors?: () => void;
  fixingErrors?: boolean;
}

export const PDFViewer: React.FC<PDFViewerProps> = ({
  pdfBase64,
  errorLog,
  loading,
  onFixErrors,
  fixingErrors,
}) => {
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);

  useEffect(() => {
    if (pdfBase64) {
      const byteCharacters = atob(pdfBase64);
      const byteNumbers = new Array(byteCharacters.length);
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
      }
      const byteArray = new Uint8Array(byteNumbers);
      const blob = new Blob([byteArray], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      setPdfUrl(url);
      return () => URL.revokeObjectURL(url);
    } else {
      setPdfUrl(null);
    }
  }, [pdfBase64]);

  const downloadPDF = () => {
    if (pdfUrl) {
      const link = document.createElement('a');
      link.href = pdfUrl;
      link.download = 'document.pdf';
      link.click();
    }
  };

  const hasErrors = errorLog && errorLog.trim() !== '';

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200 dark:border-gray-700 bg-gradient-to-r from-slate-300 via-blue-300 to-indigo-300 dark:from-slate-800 dark:to-slate-900">
        <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-500"></span>
          PDF Preview
        </h3>
        {pdfUrl && (
          <button
            onClick={downloadPDF}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded-lg transition-all"
          >
            <Download className="w-3.5 h-3.5" />
            Download
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 relative bg-gradient-to-br from-slate-300 via-blue-300 to-indigo-300 dark:from-slate-950 dark:via-indigo-950 dark:to-blue-950">
        {/* Loading */}
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/80 dark:bg-gray-900/80 backdrop-blur-sm z-10">
            <div className="text-center">
              <div className="w-16 h-16 bg-blue-100 dark:bg-blue-900/30 rounded-2xl flex items-center justify-center mx-auto mb-4 animate-pulse">
                <Loader2 className="w-8 h-8 animate-spin text-blue-600" />
              </div>
              <p className="text-sm font-medium text-gray-700 dark:text-gray-300">Compiling document...</p>
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">This may take a few seconds</p>
            </div>
          </div>
        )}

        {/* Errors */}
        {!loading && hasErrors && (
          <div className="p-4 h-full overflow-auto">
            <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-5 mb-4">
              <div className="flex items-start gap-3 mb-3">
                <div className="w-10 h-10 bg-amber-100 dark:bg-amber-800 rounded-xl flex items-center justify-center flex-shrink-0">
                  <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                </div>
                <div>
                  <h4 className="font-semibold text-amber-800 dark:text-amber-300 mb-1">Compilation Error</h4>
                  <p className="text-sm text-amber-700 dark:text-amber-400">
                    Your LaTeX document has errors. AI can analyze and fix them automatically.
                  </p>
                </div>
              </div>
              {onFixErrors && (
                <button
                  onClick={onFixErrors}
                  disabled={fixingErrors}
                  className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-semibold rounded-xl transition-all ${
                    fixingErrors
                      ? 'bg-gray-200 dark:bg-gray-700 text-gray-400 cursor-not-allowed'
                      : 'bg-gradient-to-r from-amber-500 to-orange-500 text-white hover:from-amber-600 hover:to-orange-600 shadow-md hover:shadow-lg active:scale-[0.98]'
                  }`}
                >
                  {fixingErrors ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Sparkles className="w-4 h-4" />
                  )}
                  {fixingErrors ? 'AI is fixing errors...' : 'Fix Errors with AI'}
                </button>
              )}
            </div>

            <div className="bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
              <h5 className="font-medium text-gray-800 dark:text-gray-200 mb-2 flex items-center gap-2">
                <FileText className="w-4 h-4 text-gray-400" />
                Error Details
              </h5>
              <pre className="text-xs text-gray-600 dark:text-gray-400 whitespace-pre-wrap overflow-auto max-h-64 font-mono bg-gray-100 dark:bg-gray-900 p-3 rounded-lg">
                {errorLog}
              </pre>
            </div>
          </div>
        )}

        {/* PDF Preview */}
        {!loading && !hasErrors && pdfUrl && (
          <iframe
            src={pdfUrl}
            className="w-full h-full border-0"
            title="PDF Preview"
          />
        )}

        {/* Empty state */}
        {!loading && !hasErrors && !pdfUrl && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <div className="w-20 h-20 bg-gray-100 dark:bg-gray-800 rounded-2xl flex items-center justify-center mx-auto mb-4">
                <FileText className="w-10 h-10 text-gray-300 dark:text-gray-600" />
              </div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Ready to compile</p>
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">Click <span className="font-semibold text-blue-500">Compile</span> to generate PDF</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};