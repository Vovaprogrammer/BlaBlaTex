import { useEffect, useMemo, useRef } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { EditorState, type Extension } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { StreamLanguage, HighlightStyle, syntaxHighlighting } from '@codemirror/language';
import { stex } from '@codemirror/legacy-modes/mode/stex';
import { tags } from '@lezer/highlight';
import { useTheme } from '@/app/theme-context';
import type { EditorTarget } from './editor-navigation';

export function SourceEditor({
  path,
  value,
  readOnly = false,
  onChange,
  onCreate,
  extra,
  target,
}: {
  path: string;
  value: string;
  readOnly?: boolean;
  onChange: (text: string) => void;
  onCreate?: (view: EditorView) => void;
  extra?: Extension;
  target?: EditorTarget;
}) {
  const viewRef = useRef<EditorView | null>(null);
  const applied = useRef<EditorTarget | undefined>(undefined);
  function jump(view: EditorView) {
    if (!target || target.path !== path || applied.current === target) return;
    const position = view.state.doc.line(Math.min(target.line, view.state.doc.lines)).from;
    view.dispatch({
      selection: { anchor: position },
      effects: EditorView.scrollIntoView(position, { y: 'center' }),
    });
    view.focus();
    applied.current = target;
  }
  useEffect(() => {
    if (viewRef.current) jump(viewRef.current);
  });
  const { theme } = useTheme();
  const extensions = useMemo(
    () => [
      ...(extra ? [extra] : []),
      EditorView.lineWrapping,
      EditorView.contentAttributes.of({
        'aria-label': `Редактор ${path}`,
        'aria-readonly': String(readOnly),
        spellcheck: 'false',
      }),
      EditorState.phrases.of({
        Find: 'Найти',
        Replace: 'Заменить',
        next: 'далее',
        previous: 'назад',
        all: 'все',
        'match case': 'учитывать регистр',
        'by word': 'слово целиком',
        regexp: 'регулярное выражение',
        replace: 'заменить',
        'replace all': 'заменить всё',
        close: 'закрыть',
        Search: 'Поиск',
        'No matches': 'Совпадений нет',
        'current match': 'текущее совпадение',
        'replaced $ matches': 'Заменено совпадений: $',
      }),
      ...(/\.(tex|sty|cls|bib)$/i.test(path) ? [StreamLanguage.define(stex)] : []),
      syntaxHighlighting(
        HighlightStyle.define([
          { tag: [tags.keyword, tags.atom, tags.number, tags.meta], color: 'var(--ring)' },
          { tag: tags.comment, color: 'var(--muted-foreground)', fontStyle: 'italic' },
        ]),
      ),
      EditorView.theme(
        {
          '&': {
            height: '100%',
            color: 'var(--foreground)',
            backgroundColor: 'var(--card)',
            fontSize: '14px',
          },
          '.cm-scroller': { overflow: 'auto', fontFamily: 'monospace' },
          '.cm-content': { minHeight: '100%', padding: '12px 0' },
          '.cm-gutters': {
            color: 'var(--muted-foreground)',
            backgroundColor: 'var(--secondary)',
            borderRight: '1px solid var(--border)',
          },
          '.cm-activeLine, .cm-activeLineGutter': { backgroundColor: 'var(--muted)' },
          '.cm-cursor': { borderLeftColor: 'var(--foreground)' },
          '&.cm-focused .cm-selectionBackground, .cm-selectionBackground': {
            backgroundColor: 'var(--accent)',
          },
          '.cm-panels': { backgroundColor: 'var(--secondary)', color: 'var(--foreground)' },
          '.cm-textfield': {
            backgroundColor: 'var(--card)',
            color: 'var(--foreground)',
            border: '1px solid var(--border)',
          },
        },
        { dark: theme === 'dark' },
      ),
    ],
    [path, readOnly, theme, extra],
  );
  return (
    <CodeMirror
      value={value}
      height="100%"
      theme="none"
      extensions={extensions}
      readOnly={readOnly}
      editable={!readOnly}
      onChange={(text) => onChange(text)}
      onCreateEditor={(view) => {
        viewRef.current = view;
        jump(view);
        onCreate?.(view);
      }}
      placeholder="Файл пуст"
      indentWithTab={false}
      basicSetup={{ lineNumbers: true, foldGutter: true, searchKeymap: true }}
      className="h-full min-h-0"
    />
  );
}
