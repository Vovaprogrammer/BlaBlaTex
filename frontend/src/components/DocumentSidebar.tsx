import React, { useState, useEffect } from 'react';
import {
  File,
  Plus,
  Search,
  Trash2,
  Edit3,
  Loader2,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { apiService } from '../services/api';
import type { Document } from '../types/api';

interface DocumentSidebarProps {
  currentDocument: Document | null;
  onSelectDocument: (document: Document) => void;
  onNewDocument: () => void;
}

export const DocumentSidebar: React.FC<DocumentSidebarProps> = ({
  currentDocument,
  onSelectDocument,
  onNewDocument,
}) => {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [editingTitle, setEditingTitle] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState('');
  const [isCollapsed, setIsCollapsed] = useState(false);

  useEffect(() => {
    loadDocuments();
  }, []);

  const loadDocuments = async () => {
    setLoading(true);
    try {
      const docs = await apiService.getDocuments();
      setDocuments(docs);
    } catch (error: any) {
      console.error('Failed to load documents:', error);
      if (error?.message && error.message.toLowerCase().includes('unauthorized')) {
        alert('Session expired. Please sign in again.');
        return;
      }
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteDocument = async (docId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Are you sure you want to delete this document?')) return;

    try {
      await apiService.deleteDocument(docId);
      setDocuments(docs => docs.filter(doc => doc.id !== docId));
      if (currentDocument?.id === docId) {
        onNewDocument();
      }
    } catch (error) {
      console.error('Failed to delete document:', error);
      alert('Failed to delete document. Please try again.');
    }
  };

  const handleRenameDocument = async (docId: string, title: string) => {
    try {
      const doc = documents.find(d => d.id === docId);
      if (!doc) return;

      const updated = await apiService.updateDocument(docId, {
        title,
        content: doc.content,
      });

      setDocuments(docs => docs.map(d => (d.id === docId ? updated : d)));
      setEditingTitle(null);
    } catch (error) {
      console.error('Failed to rename document:', error);
      alert('Failed to rename document. Please try again.');
    }
  };

  const filteredDocuments = documents.filter(doc =>
    doc.title.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (loading) {
    return (
      <div className={`transition-all duration-300 ${isCollapsed ? 'w-16' : 'w-80'} bg-gradient-to-b from-blue-600 via-indigo-600 to-purple-600 dark:from-slate-950 dark:via-indigo-950 dark:to-blue-950 border-r border-gray-200 dark:border-gray-700 p-4 flex flex-col items-center justify-center`}>
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="p-2 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-full transition-colors self-start mb-4"
          title={isCollapsed ? "Expand" : "Collapse"}
        >
          {isCollapsed ? <ChevronRight className="w-6 h-6" /> : <ChevronLeft className="w-6 h-6" />}
        </button>
        <Loader2 className="w-6 h-6 animate-spin text-blue-600" />
      </div>
    );
  }

  return (
    <div className={`transition-all duration-300 ${isCollapsed ? 'w-16' : 'w-80'} bg-gradient-to-b from-blue-600 via-indigo-600 to-purple-600 dark:from-slate-950 dark:via-indigo-950 dark:to-blue-950 border-r border-gray-200 dark:border-gray-700 flex flex-col`}>
      <div className="p-4 border-b border-gray-200 dark:border-gray-700">
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="p-2 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-full transition-colors"
          title={isCollapsed ? "Expand" : "Collapse"}
        >
          {isCollapsed ? <ChevronRight className="w-6 h-6" /> : <ChevronLeft className="w-6 h-6" />}
        </button>
      </div>

      {!isCollapsed && (
        <>
          <div className="p-4 border-b border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-2 mb-4">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Documents</h2>
              <button
                onClick={onNewDocument}
                className="ml-auto p-2 text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded-lg transition-colors"
              >
                <Plus className="w-5 h-5" />
              </button>
            </div>

            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 dark:text-gray-500 w-4 h-4" />
              <input
                type="text"
                placeholder="Search documents..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-10 pr-4 py-2 border border-gray-200 dark:border-gray-600 bg-white/80 dark:bg-gray-800/80 text-gray-900 dark:text-white rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder-gray-400 dark:placeholder-gray-500"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto">
            {filteredDocuments.length === 0 ? (
              <div className="p-6 text-center">
                <div className="w-16 h-16 bg-gray-100 dark:bg-gray-800 rounded-2xl flex items-center justify-center mx-auto mb-3">
                  {searchTerm ? (
                    <Search className="w-8 h-8 text-gray-300 dark:text-gray-600" />
                  ) : (
                    <File className="w-8 h-8 text-gray-300 dark:text-gray-600" />
                  )}
                </div>
                <p className="text-sm font-medium text-gray-500 dark:text-gray-400">
                  {searchTerm ? 'No documents found' : 'No documents yet'}
                </p>
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                  {searchTerm ? 'Try a different search term' : 'Click + to create your first document'}
                </p>
              </div>
            ) : (
              <div className="p-2">
                {filteredDocuments.map((doc) => (
                  <div
                    key={doc.id}
                    className={`group flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-colors ${
                      currentDocument?.id === doc.id
                        ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-900 dark:text-blue-100'
                        : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
                    }`}
                    onClick={() => onSelectDocument(doc)}
                  >
                    <File className="w-4 h-4 flex-shrink-0 text-gray-400 dark:text-gray-400" />

                    {editingTitle === doc.id ? (
                      <input
                        type="text"
                        value={newTitle}
                        onChange={(e) => setNewTitle(e.target.value)}
                        onBlur={() => handleRenameDocument(doc.id, newTitle)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleRenameDocument(doc.id, newTitle);
                          if (e.key === 'Escape') setEditingTitle(null);
                        }}
                        className="flex-1 bg-white/80 dark:bg-gray-800/80 border border-blue-300 dark:border-blue-600 text-gray-900 dark:text-white rounded px-2 py-1 text-sm"
                        autoFocus
                        onClick={(e) => e.stopPropagation()}
                      />
                    ) : (
                      <span className="flex-1 text-sm font-medium truncate">
                        {doc.title}
                      </span>
                    )}

                    <div className="opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setEditingTitle(doc.id);
                          setNewTitle(doc.title);
                        }}
                        className="p-1 text-gray-400 dark:text-gray-500 hover:text-blue-600 dark:hover:text-blue-400 rounded"
                      >
                        <Edit3 className="w-3 h-3" />
                      </button>
                      <button
                        onClick={(e) => handleDeleteDocument(doc.id, e)}
                        className="p-1 text-gray-400 dark:text-gray-500 hover:text-red-600 rounded"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {isCollapsed && (
        <div className="flex-1 overflow-y-auto p-2">
          {filteredDocuments.map((doc) => (
            <div
              key={doc.id}
              className={`flex items-center justify-center p-3 rounded-lg cursor-pointer transition-colors mb-2 ${
                currentDocument?.id === doc.id
                  ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-900 dark:text-blue-100'
                  : 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'
              }`}
              onClick={() => onSelectDocument(doc)}
              title={doc.title}
            >
              <File className="w-4 h-4 text-gray-400 dark:text-gray-400" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
};