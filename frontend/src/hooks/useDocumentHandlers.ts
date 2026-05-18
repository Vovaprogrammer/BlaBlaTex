import { useState, useCallback, useEffect, useRef } from 'react';
import { apiService } from '../services/api';
import type { Document, CompileResponse } from '../types/api';
import { NEW_DOCUMENT_TEMPLATE } from '../constants/newDocumentTemplate';

export function useDocumentHandlers() {
  const [currentDocument, setCurrentDocument] = useState<Document | null>(null);
  const [content, setContent] = useState('');
  const [title, setTitle] = useState('Untitled Document');
  const [compileResult, setCompileResult] = useState<CompileResponse | null>(null);
  const [compiling, setCompiling] = useState(false);
  const [fixingErrors, setFixingErrors] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [documentsList, setDocumentsList] = useState<Document[]>([]);

  const latestContentRef = useRef(content);
  const latestTitleRef = useRef(title);
  const latestCurrentDocumentRef = useRef(currentDocument);

  useEffect(() => {
    latestContentRef.current = content;
    latestTitleRef.current = title;
    latestCurrentDocumentRef.current = currentDocument;
  }, [content, title, currentDocument]);

  const loadDocuments = useCallback(async () => {
    try { const docs = await apiService.getDocuments(); setDocumentsList(docs); return docs; }
    catch (error) { console.error('Failed to load documents:', error); return []; }
  }, []);

  const saveDocument = useCallback(async (): Promise<Document | null> => {
    if (isSaving) return currentDocument;
    setIsSaving(true);
    try {
      let savedDoc;
      if (latestCurrentDocumentRef.current) {
        savedDoc = await apiService.updateDocument(latestCurrentDocumentRef.current.id, { title: latestTitleRef.current, content: latestContentRef.current });
        setCurrentDocument(savedDoc);
        setDocumentsList(prev => prev.map(doc => doc.id === savedDoc.id ? savedDoc : doc));
      } else {
        if (!latestContentRef.current || latestContentRef.current.trim().length === 0) { setIsSaving(false); return null; }
        savedDoc = await apiService.createDocument({ title: latestTitleRef.current, content: latestContentRef.current });
        setCurrentDocument(savedDoc);
        setDocumentsList(prev => [savedDoc, ...prev]);
      }
      setHasUnsavedChanges(false);
      return savedDoc;
    } catch (error) { console.error('Failed to save document:', error); return null; }
    finally { setIsSaving(false); }
  }, [isSaving]);

  useEffect(() => {
    const interval = setInterval(() => {
      if (hasUnsavedChanges && !isSaving && latestContentRef.current && latestContentRef.current.trim().length > 0) { saveDocument(); }
    }, 5000);
    return () => clearInterval(interval);
  }, [hasUnsavedChanges, isSaving, saveDocument]);

  const handleDocumentSelect = useCallback(async (doc: Document) => {
    if (hasUnsavedChanges && !isSaving) { if (window.confirm('You have unsaved changes. Save before switching?')) await saveDocument(); }
    try {
      const freshDoc = await apiService.getDocument(doc.id);
      setCurrentDocument(freshDoc); setContent(freshDoc.content); setTitle(freshDoc.title); setHasUnsavedChanges(false); setCompileResult(null);
    } catch (error) {
      setCurrentDocument(doc); setContent(doc.content); setTitle(doc.title); setHasUnsavedChanges(false);
    }
  }, [hasUnsavedChanges, isSaving, saveDocument]);

  const handleNewDocument = useCallback(() => {
    if (hasUnsavedChanges && !isSaving) { if (window.confirm('You have unsaved changes. Save before creating new document?')) saveDocument(); }
    setCurrentDocument(null); setTitle('Untitled Document'); setContent(NEW_DOCUMENT_TEMPLATE); setHasUnsavedChanges(false); setCompileResult(null);
  }, [hasUnsavedChanges, isSaving, saveDocument]);

  const handleContentChange = (newContent: string) => { setContent(newContent); setHasUnsavedChanges(true); };

  const handleCompile = async (compiler: string = 'pdflatex') => {
    if (!isSaving) await saveDocument();
    setCompiling(true);
    try { const result = await apiService.compileDocument(latestContentRef.current, compiler); setCompileResult(result); }
    catch (error) { setCompileResult({ pdf_base64: '', error_log: error instanceof Error ? error.message : 'Compilation failed' }); }
    finally { setCompiling(false); }
  };

  const handleFixErrors = async () => {
    if (!compileResult?.error_log) return;
    setFixingErrors(true);
    try { const result = await apiService.fixErrors({ code: content, errors: compileResult.error_log }); setContent(result.code); setHasUnsavedChanges(true); setTimeout(() => handleCompile(), 500); }
    catch (error) { console.error('Failed to fix errors:', error); }
    finally { setFixingErrors(false); }
  };

  const handleInsertCode = (code: string) => {
    const textarea = document.querySelector('textarea');
    if (textarea) {
      const start = textarea.selectionStart; const end = textarea.selectionEnd;
      const newContent = content.substring(0, start) + code + content.substring(end);
      setContent(newContent); setHasUnsavedChanges(true);
      setTimeout(() => { textarea.focus(); textarea.selectionStart = textarea.selectionEnd = start + code.length; }, 0);
    } else { setContent(prev => prev + '\n\n' + code); setHasUnsavedChanges(true); }
  };

  const handleReplaceCode = (code: string) => { setContent(code); setHasUnsavedChanges(true); };

  useEffect(() => { loadDocuments(); }, [loadDocuments]);

  return {
    state: { currentDocument, content, title, compileResult, compiling, fixingErrors, hasUnsavedChanges, isSaving, documentsList },
    setters: { setTitle, setContent, setCurrentDocument, setCompileResult, setHasUnsavedChanges, setDocumentsList },
    handlers: { handleDocumentSelect, handleNewDocument, saveDocument, handleContentChange, handleCompile, handleFixErrors, handleInsertCode, handleReplaceCode, loadDocuments },
  };
}