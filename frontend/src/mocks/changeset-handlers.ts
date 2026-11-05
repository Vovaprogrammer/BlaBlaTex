import { http, HttpResponse } from 'msw';
import { mockState, newFile, ownedProject, type Schemas } from './data';
import { emitMockEvent } from './project-events';
import { failure, guard } from './responses';

type Example = { project: string; diff: Schemas['ChangesetDiff']; texts: Map<string, string> };
const states = new WeakMap<typeof mockState.current, Map<string, Example>>();
export function addExampleChangeset(project: string, run: Schemas['RunOut']) {
  const record = ownedProject(project);
  if (!record) return false;
  const texts = new Map([
    [
      'results.tex',
      '\\section{Результаты}\n\\subsection{Измерения}\nДобавьте таблицу исходных данных.\n',
    ],
    ['conclusion.tex', '\\section{Вывод}\nСформулируйте вывод на основе измерений.\n'],
  ]);
  if ([...texts.keys()].some((path) => record.files.has(path))) return false;

  let examples = states.get(mockState.current);
  if (!examples) states.set(mockState.current, (examples = new Map()));
  const now = new Date().toISOString();
  const changeset: Schemas['ChangesetOut'] = {
    id: run.changeset_id,
    author: 'ai',
    message: null,
    run_id: run.id,
    reverts_id: null,
    reverted_by: null,
    created_at: now,
    updated_at: now,
  };
  const files: Schemas['FileDiff'][] = [];
  for (const [path, text] of texts) {
    const lines = text.trimEnd().split('\n');
    files.push({
      path,
      old_path: null,
      change: 'added',
      kind: 'text',
      additions: lines.length,
      deletions: 0,
      diff: `--- /dev/null\n+++ b/${path}\n@@ -0,0 +1,${lines.length} @@\n${lines.map((line) => '+' + line).join('\n')}\n`,
      too_large: false,
    });
    const file = newFile(path, text);
    record.files.set(path, file);
    emitMockEvent(project, {
      event: 'file.changed',
      data: { path, version: file.info.version, author: 'ai', changeset_id: changeset.id },
    });
  }
  examples.set(changeset.id, { project, diff: { changeset, files }, texts });
  return true;
}

const lookup = (cid: string) => states.get(mockState.current)?.get(cid);
export const changesetHandlers = [
  http.get('/api/v1/changesets/:cid/diff', ({ request, params }) => {
    const auth = guard(request);
    if (auth) return auth;
    const example = lookup(String(params.cid));
    if (!example || !ownedProject(example.project))
      return failure(404, 'not_found', 'Правки не найдены.');
    return HttpResponse.json(example.diff);
  }),
  http.post('/api/v1/changesets/:cid/revert', ({ request, params }) => {
    const auth = guard(request);
    if (auth) return auth;
    const example = lookup(String(params.cid));
    const record = example && ownedProject(example.project);
    if (!record || !example) return failure(404, 'not_found', 'Правки не найдены.');
    const files = [...example.texts].flatMap(([path, text]) => {
      const actual = record.files.get(path);
      return actual && (actual.text !== text || actual.info.kind !== 'text')
        ? [{ path, reason: 'changed' }]
        : [];
    });
    if (files.length)
      return failure(409, 'revert_conflict', 'После правок агента файлы изменились.', { files });
    const paths = [...example.texts.keys()].filter((path) => record.files.has(path));
    if (!paths.length)
      return failure(
        409,
        'revert_conflict',
        'Откатывать нечего: файлы уже такие, как до этих правок',
        { files: [] },
      );
    const now = new Date().toISOString();
    const changeset: Schemas['ChangesetOut'] = {
      id: crypto.randomUUID(),
      author: 'user',
      message: null,
      run_id: null,
      reverts_id: example.diff.changeset.id,
      reverted_by: null,
      created_at: now,
      updated_at: now,
    };
    // Как бэкенд: после перезагрузки карточка узнаёт об откате из diff.
    example.diff = {
      ...example.diff,
      changeset: { ...example.diff.changeset, reverted_by: changeset.id },
    };
    for (const path of paths) {
      record.files.delete(path);
      emitMockEvent(example.project, {
        event: 'file.deleted',
        data: { path, changeset_id: changeset.id },
      });
    }
    return HttpResponse.json(changeset, { status: 201 });
  }),
];
