import { useState } from 'react';
import { SourceEditor } from './source-editor';

export function EditorPreview({
  path,
  text,
  readOnly,
}: {
  path: string;
  text: string;
  readOnly: boolean;
}) {
  const [draft, setDraft] = useState(text);
  return <SourceEditor path={path} value={draft} readOnly={readOnly} onChange={setDraft} />;
}
