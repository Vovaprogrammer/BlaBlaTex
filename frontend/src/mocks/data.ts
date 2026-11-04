import type { components } from '@/api/schema';

export type Schemas = components['schemas'];
export const demoId = '00000000-0000-4000-8000-000000000001';
export const demoPassword = 'demo-password';
export const timestamp = '2026-01-01T00:00:00Z';
export const template: Schemas['TemplateDetail'] = {
  slug: 'demo-lab',
  version: 1,
  kind: 'lab',
  title: 'Учебный шаблон',
  discipline: 'Демонстрационная дисциплина',
  fields: [
    {
      key: 'report_title',
      label: 'Название работы',
      type: 'string',
      required: true,
      default: null,
      options: [],
    },
    {
      key: 'lab_number',
      label: 'Номер работы',
      type: 'int',
      required: false,
      default: 1,
      options: [],
    },
    {
      key: 'comment',
      label: 'Комментарий',
      type: 'text',
      required: false,
      default: '',
      options: [],
    },
    {
      key: 'variant',
      label: 'Вариант',
      type: 'select',
      required: false,
      default: 'А',
      options: ['А', 'Б'],
    },
  ],
  sections: [
    {
      id: 'goal',
      title: 'Цель работы',
      file: 'main.tex',
      required: true,
      guide: 'Сформулируйте цель по материалам.',
    },
  ],
};

export function emptyProfile(): Schemas['ProfileOut'] {
  return {
    last_name: '',
    first_name: '',
    middle_name: '',
    group_name: '',
    faculty: '',
    department: '',
    updated_at: timestamp,
  };
}
export function newFile(
  path: string,
  text = '',
  role: Schemas['FileInfo']['role'] = 'source',
): { info: Schemas['FileInfo']; text: string; blob?: Blob } {
  return {
    info: {
      path,
      kind: 'text',
      role,
      mime: 'text/plain',
      size: new TextEncoder().encode(text).length,
      version: 1,
      updated_at: timestamp,
    },
    text,
  };
}
export function newProject(id = demoId): Schemas['ProjectOut'] {
  return {
    id,
    title: 'Учебный отчёт',
    kind: 'lab',
    template_slug: template.slug,
    template_version: 1,
    fields: { report_title: 'Учебный отчёт', lab_number: 1, variant: 'А', comment: '' },
    main_file: 'main.tex',
    engine: 'xelatex',
    created_at: timestamp,
    updated_at: timestamp,
  };
}
function initialState() {
  const account = {
    user: {
      id: demoId,
      email: 'student@example.com',
      role: 'student',
      created_at: timestamp,
    } satisfies Schemas['UserOut'],
    profile: emptyProfile(),
    password: demoPassword,
  };
  return {
    currentUserId: demoId as string | null,
    accounts: new Map([[demoId, account]]),
    projects: new Map([
      [
        demoId,
        {
          project: newProject(),
          owner: demoId,
          files: new Map([
            [
              'main.tex',
              newFile(
                'main.tex',
                '\\documentclass{article}\n\\begin{document}\n\\section{Цель работы}\n\\end{document}\n',
              ),
            ],
            ['meta.tex', newFile('meta.tex', '% Создаётся автоматически.\n', 'generated')],
          ]),
        },
      ],
    ]),
    builds: new Map<string, Schemas['BuildOut']>(),
  };
}
export const mockState = { current: initialState() };
export function resetMockState() {
  mockState.current = initialState();
}
export function currentAccount() {
  return mockState.current.accounts.get(mockState.current.currentUserId ?? '');
}
export function ownedProject(id: string) {
  const value = mockState.current.projects.get(id);
  return value?.owner === mockState.current.currentUserId ? value : undefined;
}
export function refreshGeneratedFiles(owner: string, projectId?: string) {
  for (const value of mockState.current.projects.values()) {
    if (value.owner !== owner || (projectId && value.project.id !== projectId)) continue;
    const meta = value.files.get('meta.tex');
    if (meta) {
      meta.info.version++;
      meta.info.updated_at = new Date().toISOString();
    }
  }
}
