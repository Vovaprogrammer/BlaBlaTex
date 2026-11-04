import { mockState, ownedProject, type Schemas } from './data';
import { emitMockEvent } from './project-events';

const texts = new WeakMap<typeof mockState.current, Map<string, Schemas['MaterialTextOut']>>();
function records() {
  let value = texts.get(mockState.current);
  if (!value) {
    value = new Map();
    texts.set(mockState.current, value);
  }
  return value;
}
export function materialText(project: string, path: string): Schemas['MaterialTextOut'] {
  const file = ownedProject(project)!.files.get(path)!;
  const text =
    file.info.kind === 'text'
      ? file.text
      : 'Тестовый режим: извлечение текста из этого файла не выполнялось.';
  return (
    records().get(`${project}/${path}`) ?? {
      path,
      status: 'ready',
      method: file.info.kind === 'text' ? 'text' : null,
      pages: null,
      description: null,
      error: null,
      text,
      offset: 0,
      total: text.length,
    }
  );
}
export function prepareMaterialText(project: string, path: string) {
  const state = mockState.current;
  const file = ownedProject(project)!.files.get(path)!;
  const values = records();
  values.delete(`${project}/${path}`);
  const ready = materialText(project, path);
  const text =
    file.info.kind === 'text'
      ? file.text
      : 'Тестовый режим: извлечение текста из этого файла не выполнялось.';
  values.set(`${project}/${path}`, {
    ...ready,
    status: 'pending',
    text: null,
    method: null,
    total: 0,
  });
  setTimeout(() => {
    if (mockState.current !== state || ownedProject(project)?.files.get(path) !== file) return;
    values.set(`${project}/${path}`, { ...ready, status: 'ready', text, total: text.length });
    emitMockEvent(project, { event: 'material.ready', data: { path, status: 'ready' } });
  }, 800);
}
