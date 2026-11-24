import { http, HttpResponse } from 'msw/http';
import { ownedProject, type Schemas } from './data';
import { guard, failure } from './responses';

export const checkHandlers = [
  http.post('/api/v1/projects/:pid/checks', ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    if (!ownedProject(String(params.pid))) return failure(404, 'not_found', 'Проект не найден');
    // Фикстура для просмотра переходов; реальные проверки выполняет сервер.
    return HttpResponse.json<Schemas['CheckResult']>({
      findings: [
        {
          check: 'title-empty',
          level: 'error',
          message: 'Не заполнено поле «Название работы».',
          place: 'fields',
          field: 'report_title',
          file: null,
          line: null,
        },
        {
          check: 'ref-broken',
          level: 'error',
          message: 'Ссылка на рисунок не найдена.',
          place: 'file',
          field: null,
          file: 'main.tex',
          line: 3,
        },
        {
          check: 'title-empty',
          level: 'warning',
          message: 'Проверьте группу в профиле.',
          place: 'profile',
          field: 'group_name',
          file: null,
          line: null,
        },
      ],
      errors_count: 2,
      warnings_count: 1,
      pdf_checked: true,
      build_id: null,
    });
  }),
];
