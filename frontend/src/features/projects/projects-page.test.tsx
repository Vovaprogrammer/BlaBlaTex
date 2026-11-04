import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { expect, test } from 'vitest';
import { renderApp } from '@/test/render-app';
import { mockState, demoId } from '@/mocks/data';
import { server } from '@/test/server';
import { failure } from '@/mocks/responses';

test('список показывает реальные проекты, фильтрует и открывает рабочее окно', async () => {
  renderApp('/projects');
  const user = userEvent.setup();
  const project = mockState.current.projects.get(demoId)!.project;
  await screen.findByRole('heading', { name: project.title });
  await user.type(screen.getByRole('searchbox', { name: 'Поиск проектов' }), 'Нет такого');
  expect(screen.getByRole('heading', { name: 'Проекты не найдены' })).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Сбросить фильтры' }));
  await user.click(screen.getByRole('link', { name: new RegExp(project.title) }));
  expect(await screen.findByRole('heading', { name: 'Рабочее окно' })).toBeInTheDocument();
});
test('пустой список предлагает создать первый проект', async () => {
  mockState.current.projects.clear();
  renderApp('/projects');
  expect(await screen.findByRole('heading', { name: 'Пока нет проектов' })).toBeInTheDocument();
});
test('ошибка загрузки не выглядит пустым списком и позволяет повторить запрос', async () => {
  server.use(http.get('/api/v1/projects', () => failure(500, 'internal', 'Список недоступен')));
  renderApp('/projects');
  expect(await screen.findByRole('alert')).toHaveTextContent('Список недоступен');
  expect(screen.queryByRole('heading', { name: 'Пока нет проектов' })).not.toBeInTheDocument();
  server.resetHandlers();
  await userEvent
    .setup()
    .click(screen.getByRole('button', { name: 'Повторить загрузку проектов' }));
  expect(
    await screen.findByRole('heading', {
      name: mockState.current.projects.get(demoId)!.project.title,
    }),
  ).toBeInTheDocument();
});
