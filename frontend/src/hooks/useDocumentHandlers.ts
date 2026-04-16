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
  
  // Рефы для автосохранения
  const latestContentRef = useRef(content);
  const latestTitleRef = useRef(title);
  const latestCurrentDocumentRef = useRef(currentDocument);
  
  useEffect(() => {
    latestContentRef.current = content;
    latestTitleRef.current = title;
    latestCurrentDocumentRef.current = currentDocument;
  }, [content, title, currentDocument]);

  // Загрузка списка документов
  const loadDocuments = useCallback(async () => {
    try {
      const docs = await apiService.getDocuments();
      setDocumentsList(docs);
      return docs;
    } catch (error) {
      console.error('Failed to load documents:', error);
      return [];
    }
  }, []);

  // Функция сохранения
  const saveDocument = useCallback(async (): Promise<Document | null> => {
    if (isSaving) return currentDocument;
    
    setIsSaving(true);
    try {
      let savedDoc;
      if (latestCurrentDocumentRef.current) {
        // Обновляем существующий документ
        savedDoc = await apiService.updateDocument(
          latestCurrentDocumentRef.current.id, 
          { title: latestTitleRef.current, content: latestContentRef.current }
        );
        setCurrentDocument(savedDoc);
        // Обновляем документ в списке
        setDocumentsList(prev => prev.map(doc => 
          doc.id === savedDoc.id ? savedDoc : doc
        ));
      } else {
        // Создаём новый документ
        savedDoc = await apiService.createDocument({ 
          title: latestTitleRef.current, 
          content: latestContentRef.current 
        });
        setCurrentDocument(savedDoc);
        setDocumentsList(prev => [savedDoc, ...prev]);
      }
      setHasUnsavedChanges(false);
      console.log('Document saved successfully');
      return savedDoc;
    } catch (error) {
      console.error('Failed to save document:', error);
      return null;
    } finally {
      setIsSaving(false);
    }
  }, [isSaving]);

  // Автосохранение каждые 5 секунд
  useEffect(() => {
    const interval = setInterval(() => {
      if (hasUnsavedChanges && !isSaving && latestContentRef.current) {
        console.log('Auto-saving (5s interval)...');
        saveDocument();
      }
    }, 5000);
    
    return () => clearInterval(interval);
  }, [hasUnsavedChanges, isSaving, saveDocument]);

  const handleDocumentSelect = useCallback(async (doc: Document) => {
    // Проверяем, есть ли несохранённые изменения
    if (hasUnsavedChanges && !isSaving) {
      const confirmSave = window.confirm('You have unsaved changes. Save before switching?');
      if (confirmSave) {
        await saveDocument();
      }
    }
    
    // Загружаем свежую версию документа из БД
    try {
      const freshDoc = await apiService.getDocument(doc.id);
      setCurrentDocument(freshDoc);
      setContent(freshDoc.content);
      setTitle(freshDoc.title);
      setHasUnsavedChanges(false);
      setCompileResult(null);
    } catch (error) {
      console.error('Failed to load document:', error);
      // Fallback к переданному документу
      setCurrentDocument(doc);
      setContent(doc.content);
      setTitle(doc.title);
      setHasUnsavedChanges(false);
    }
  }, [hasUnsavedChanges, isSaving, saveDocument]);

  const handleNewDocument = useCallback(() => {
    // Проверяем, есть ли несохранённые изменения
    if (hasUnsavedChanges && !isSaving) {
      const confirmSave = window.confirm('You have unsaved changes. Save before creating new document?');
      if (confirmSave) {
        saveDocument();
      }
    }
    
    setCurrentDocument(null);
    setTitle('Untitled Document');
    setContent(NEW_DOCUMENT_TEMPLATE);
    setHasUnsavedChanges(false);
    setCompileResult(null);
  }, [hasUnsavedChanges, isSaving, saveDocument]);

  const handleContentChange = (newContent: string) => {
    setContent(newContent);
    setHasUnsavedChanges(true);
  };

  const handleCompile = async (compiler: string = 'pdflatex') => {
    // Перед компиляцией сохраняем, если есть изменения
    if (hasUnsavedChanges && !isSaving) {
      console.log('Saving before compilation...');
      await saveDocument();
    }
    
    setCompiling(true);
    try {
      const result = await apiService.compileDocument(content, compiler);
      setCompileResult(result);
    } catch (error) {
      console.error('Compilation failed:', error);
      setCompileResult({
        pdf_base64: '',
        error_log: error instanceof Error ? error.message : 'Compilation failed',
      });
    } finally {
      setCompiling(false);
    }
  };

  const handleFixErrors = async () => {
    if (!compileResult?.error_log) return;
    setFixingErrors(true);
    try {
      const result = await apiService.fixErrors({ content, error_log: compileResult.error_log });
      setContent(result.fixed_code);
      setHasUnsavedChanges(true);
      setTimeout(() => handleCompile(), 500);
    } catch (error) {
      console.error('Failed to fix errors:', error);
    } finally {
      setFixingErrors(false);
    }
  };

  const handleInsertCode = (code: string) => {
    const textarea = document.querySelector('textarea');
    if (textarea) {
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const newContent = content.substring(0, start) + code + content.substring(end);
      setContent(newContent);
      setHasUnsavedChanges(true);
      setTimeout(() => {
        textarea.focus();
        textarea.selectionStart = textarea.selectionEnd = start + code.length;
      }, 0);
    } else {
      setContent(prev => prev + '\n\n' + code);
      setHasUnsavedChanges(true);
    }
  };

  // Загрузка документов при монтировании
  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  return {
    state: {
      currentDocument,
      content,
      title,
      compileResult,
      compiling,
      fixingErrors,
      hasUnsavedChanges,
      isSaving,
      documentsList,
    },
    setters: { setTitle, setContent, setCurrentDocument, setCompileResult, setHasUnsavedChanges, setDocumentsList },
    handlers: {
      handleDocumentSelect,
      handleNewDocument,
      saveDocument,
      handleContentChange,
      handleCompile,
      handleFixErrors,
      handleInsertCode,
      loadDocuments,
    },
  };
}