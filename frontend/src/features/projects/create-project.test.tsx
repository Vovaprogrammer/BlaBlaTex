import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, test, vi } from 'vitest';
import { renderApp } from '@/test/render-app';
import { mockState, template } from '@/mocks/data';
import { server } from '@/test/server';
import { failure, invalid } from '@/mocks/responses';
import { createProjectSchema, projectFields } from './project-form';

async function next(user: ReturnType<typeof userEvent.setup>, dialog: HTMLElement) {
  const button = within(dialog).getByRole('button', { name: 'Далее' });
  await waitFor(() => expect(button).toBeEnabled());
  await user.click(button);
}
async function open(step = 'fields') {
  renderApp('/projects');
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Новый проект' }));
  const dialog = await screen.findByRole('dialog', { name: 'Новый проект' });
  expect(within(dialog).getByRole('radio', { name: 'Лабораторная' })).toBeChecked();
  expect(within(dialog).getByRole('radio', { name: /Презентация/ })).toBeDisabled();
  await next(user, dialog);
  if (step === 'fields') {
    await next(user, dialog);
    await within(dialog).findByRole('textbox', { name: 'Название проекта' });
  }
  return { user, dialog };
}
test('форма показывает типы и defaults шаблона, создаёт проект и открывает его', async () => {
  const { user, dialog } = await open();
  expect(within(dialog).getByRole('textbox', { name: /Номер работы/ })).toHaveValue('1');
  expect(within(dialog).getByRole('combobox', { name: /Вариант/ })).toHaveValue('А');
  await user.type(within(dialog).getByRole('textbox', { name: 'Название проекта' }), 'Новый отчёт');
  const topic = within(dialog).getByRole('textbox', { name: /Название работы/ });
  expect(topic).toHaveValue('Учебный отчёт');
  await user.clear(topic);
  await user.type(topic, 'Тестовая тема');
  await user.type(
    within(dialog).getByRole('textbox', { name: /Комментарий/ }),
    'Первая строка\nВторая',
  );
  await next(user, dialog);
  await user.click(within(dialog).getByRole('button', { name: 'Создать проект' }));
  await screen.findByRole('heading', { name: 'Рабочее окно' });
  expect(await screen.findByText('Сделай отчёт по загруженным материалам')).toBeVisible();
  const project = [...mockState.current.projects.values()].find(
    (value) => value.project.title === 'Новый отчёт',
  )!.project;
  expect(project.fields).toMatchObject({
    report_title: 'Тестовая тема',
    lab_number: 1,
    comment: 'Первая строка\nВторая',
    variant: 'А',
  });
});
test('ошибка сервера показывается у динамического поля, ввод сохраняется', async () => {
  const { user, dialog } = await open();
  server.use(
    http.post('/api/v1/projects', () => invalid('fields.report_title', 'Тема не подходит')),
  );
  await user.type(within(dialog).getByRole('textbox', { name: 'Название проекта' }), 'Название');
  const topic = within(dialog).getByRole('textbox', { name: /Название работы/ });
  await user.clear(topic);
  await user.type(topic, 'Тема');
  await next(user, dialog);
  await user.click(within(dialog).getByRole('button', { name: 'Создать проект' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Тема не подходит');
  expect(within(dialog).getByRole('textbox', { name: /Название работы/ })).toHaveValue('Тема');
});
test('переключение шаблона убирает поля прежнего шаблона', async () => {
  server.use(
    http.get('/api/v1/templates', () =>
      HttpResponse.json({
        items: [template, { ...template, slug: 'other', title: 'Другой шаблон' }],
      }),
    ),
    http.get('/api/v1/templates/other', () =>
      HttpResponse.json({
        ...template,
        slug: 'other',
        fields: [
          {
            key: 'teacher',
            label: 'Преподаватель',
            type: 'string',
            required: true,
            default: null,
            options: [],
          },
        ],
      }),
    ),
  );
  const { user, dialog } = await open();
  await user.type(
    within(dialog).getByRole('textbox', { name: 'Название проекта' }),
    'Сохраняем название',
  );
  await user.click(within(dialog).getByRole('button', { name: 'Назад' }));
  await user.selectOptions(
    within(dialog).getByRole('combobox', { name: 'Шаблон документа' }),
    'other',
  );
  await next(user, dialog);
  await within(dialog).findByRole('textbox', { name: /Преподаватель/ });
  expect(
    within(dialog).queryByRole('textbox', { name: /Название работы/ }),
  ).not.toBeInTheDocument();
  expect(within(dialog).getByRole('textbox', { name: 'Название проекта' })).toHaveValue(
    'Сохраняем название',
  );
});
test('пустой набор шаблонов не позволяет отправить проект', async () => {
  server.use(http.get('/api/v1/templates', () => HttpResponse.json({ items: [] })));
  await open('templates');
  expect(await screen.findByText(/Шаблонов пока нет/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Создать проект' })).not.toBeInTheDocument();
});

test('материалы остаются в списке при возврате к данным и могут быть убраны', async () => {
  const { user, dialog } = await open();
  await user.type(
    within(dialog).getByRole('textbox', { name: 'Название проекта' }),
    'Лабораторная',
  );
  await next(user, dialog);
  const materials = within(dialog).getByRole('region', { name: 'Материалы для отчёта' });
  fireEvent.drop(within(materials).getByText(/Добавьте методичку/), {
    dataTransfer: { types: ['Files'], files: [new File(['data'], 'data.csv')] },
  });
  expect(within(materials).getByText('data.csv')).toBeVisible();
  await user.click(within(dialog).getByRole('button', { name: 'Назад' }));
  expect(within(dialog).getByRole('textbox', { name: 'Название проекта' })).toHaveValue(
    'Лабораторная',
  );
  await next(user, dialog);
  await user.click(within(dialog).getByRole('button', { name: 'Убрать data.csv' }));
  expect(within(dialog).queryByText('data.csv')).not.toBeInTheDocument();
});

test('повторная отправка после ошибки очереди использует уже созданный проект', async () => {
  const first = vi.fn(() => failure(500, 'internal', 'Очередь временно недоступна.'));
  server.use(http.post('/api/v1/projects/:pid/messages', first, { once: true }));
  const { user, dialog } = await open();
  await user.type(
    within(dialog).getByRole('textbox', { name: 'Название проекта' }),
    'Повтор запроса',
  );
  await next(user, dialog);
  await user.click(within(dialog).getByRole('button', { name: 'Создать проект' }));
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(
    'Очередь временно недоступна.',
  );
  const ids = [...mockState.current.projects.keys()];
  expect(ids).toHaveLength(2);
  expect(first).toHaveBeenCalledTimes(1);
  await user.click(within(dialog).getByRole('button', { name: 'Повторить отправку' }));
  expect(await screen.findByText('Сделай отчёт по загруженным материалам')).toBeVisible();
  expect([...mockState.current.projects.keys()]).toEqual(ids);
});
test('валидация проверяет обязательность, целые числа, варианты и преобразует только известные поля', () => {
  expect(
    createProjectSchema(template.fields).safeParse({
      title: 'Название',
      fields: { report_title: ' ', lab_number: '1.5', variant: 'неизвестный' },
    }).success,
  ).toBe(false);
  expect(
    projectFields(template.fields, {
      report_title: 'Тема',
      lab_number: '0',
      variant: '',
      unknown: 'лишнее',
    }),
  ).toMatchObject({ report_title: 'Тема', lab_number: 0 });
  expect(projectFields(template.fields, { variant: '' })).not.toHaveProperty('variant');
});
