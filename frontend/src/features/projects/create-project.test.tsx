import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, test } from 'vitest';
import { renderApp } from '@/test/render-app';
import { mockState, template } from '@/mocks/data';
import { server } from '@/test/server';
import { invalid } from '@/mocks/responses';
import { createProjectSchema, projectFields } from './project-form';

async function open() {
  renderApp('/projects');
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Новый проект' }));
  const dialog = await screen.findByRole('dialog', { name: 'Новый проект' });
  await within(dialog).findByRole('textbox', { name: 'Название проекта' });
  return { user, dialog };
}
test('форма показывает типы и defaults шаблона, создаёт проект и открывает его', async () => {
  const { user, dialog } = await open();
  expect(within(dialog).getByRole('textbox', { name: /Номер работы/ })).toHaveValue('1');
  expect(within(dialog).getByRole('combobox', { name: /Вариант/ })).toHaveValue('А');
  await user.type(within(dialog).getByRole('textbox', { name: 'Название проекта' }), 'Новый отчёт');
  await user.type(
    within(dialog).getByRole('textbox', { name: /Название работы/ }),
    'Тестовая тема',
  );
  await user.type(
    within(dialog).getByRole('textbox', { name: /Комментарий/ }),
    'Первая строка\nВторая',
  );
  await user.click(within(dialog).getByRole('button', { name: 'Создать проект' }));
  await screen.findByRole('heading', { name: 'Рабочее окно' });
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
  await user.type(within(dialog).getByRole('textbox', { name: /Название работы/ }), 'Тема');
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
  await user.selectOptions(
    within(dialog).getByRole('combobox', { name: 'Шаблон документа' }),
    'other',
  );
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
  renderApp('/projects');
  await userEvent.setup().click(await screen.findByRole('button', { name: 'Новый проект' }));
  expect(await screen.findByText(/Шаблонов пока нет/)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Создать проект' })).not.toBeInTheDocument();
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
