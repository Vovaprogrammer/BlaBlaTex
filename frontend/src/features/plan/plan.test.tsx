import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http } from 'msw';
import { expect, test } from 'vitest';
import { demoId, newFile, ownedProject } from '@/mocks/data';
import { emitMockEvent } from '@/mocks/project-events';
import { renderApp } from '@/test/render-app';
import { server } from '@/test/server';
import { invalid } from '@/mocks/responses';

test('составляет план, открывает карточку и обновляет материалы по событиям проекта', async () => {
  const user = userEvent.setup();
  const files = ownedProject(demoId)!.files;
  files.set('materials/code.py', newFile('materials/code.py', '', 'material'));
  files.set('materials/measurements.csv', newFile('materials/measurements.csv', '', 'material'));
  renderApp(`/projects/${demoId}`);

  const navigation = within(await screen.findByRole('group', { name: 'Вкладки чата' }));
  await user.click(navigation.getByRole('button', { name: 'План отчёта' }));
  expect(await screen.findByText(/План ещё не составлен/)).toBeInTheDocument();
  await user.click(navigation.getByRole('button', { name: 'Чат' }));
  const draft = screen.getByRole('textbox', { name: 'Сообщение' });
  draft.focus();
  await user.keyboard('Черновик сообщения');
  expect(draft).toHaveValue('Черновик сообщения');
  await user.click(screen.getByRole('button', { name: 'Составить план' }));
  expect(await screen.findByText('Составь план отчёта')).toBeInTheDocument();
  await user.click(
    await screen.findByRole('button', { name: 'Открыть план отчёта' }, { timeout: 4000 }),
  );
  const plan = within(screen.getByRole('region', { name: 'План отчёта' }));
  expect(await plan.findByText('code.py')).toBeInTheDocument();
  expect(plan.getByText('measurements.csv')).toBeInTheDocument();
  expect(plan.getByText('Цель работы')).toBeInTheDocument();
  expect(plan.getByText('Сформулируйте цель по материалам.')).toBeInTheDocument();

  act(() => {
    files.delete('materials/code.py');
    emitMockEvent(demoId, {
      event: 'file.deleted',
      data: { path: 'materials/code.py', changeset_id: null },
    });
  });
  expect(await plan.findByText('Материалы не назначены')).toBeInTheDocument();
  expect(plan.queryByText('code.py')).not.toBeInTheDocument();
  await user.click(navigation.getByRole('button', { name: 'Чат' }));
  expect(screen.getByRole('textbox', { name: 'Сообщение' })).toHaveValue('Черновик сообщения');
}, 10000);

async function openEditablePlan() {
  const user = userEvent.setup();
  const files = ownedProject(demoId)!.files;
  files.set('materials/code.py', newFile('materials/code.py', '', 'material'));
  files.set('materials/data.csv', newFile('materials/data.csv', '', 'material'));
  files.set('materials/screen.png', newFile('materials/screen.png', '', 'material'));
  renderApp(`/projects/${demoId}`);
  const generate = await screen.findByRole('button', { name: 'Составить план' });
  await waitFor(() => expect(generate).toBeEnabled());
  await user.click(generate);
  await user.click(
    await screen.findByRole('button', { name: 'Открыть план отчёта' }, { timeout: 4000 }),
  );
  const edit = await screen.findByRole('button', { name: 'Изменить план' });
  await waitFor(() => expect(edit).toBeEnabled());
  await user.click(edit);
  return user;
}

test('сохраняет правки и запускает отчёт по подтверждённому плану', async () => {
  const user = await openEditablePlan();
  const note = screen.getByRole('textbox', { name: 'Заметка — Цель работы' });
  await user.clear(note);
  note.focus();
  await user.keyboard('Сверить программу с измерениями.');
  expect(note).toHaveValue('Сверить программу с измерениями.');
  const add = screen.getByRole('combobox', { name: 'Добавить материал — Цель работы' });
  await user.selectOptions(add, 'materials/data.csv');
  await user.selectOptions(add, 'materials/screen.png');
  await user.click(screen.getByRole('button', { name: 'Выше: data.csv' }));
  await user.click(screen.getByRole('button', { name: 'Убрать: screen.png' }));
  await user.click(screen.getByRole('button', { name: 'Сохранить план' }));
  const panel = within(screen.getByRole('region', { name: 'План отчёта' }));
  expect(await panel.findByText('Сверить программу с измерениями.')).toBeInTheDocument();
  const sections = within(panel.getByRole('list', { name: 'Разделы отчёта' }));
  const materials = within(sections.getAllByRole('listitem')[0]!);
  expect(materials.getAllByRole('listitem').map((item) => item.textContent)).toEqual([
    'data.csv',
    'code.py',
  ]);

  await user.click(panel.getByRole('button', { name: 'Подтвердить и написать отчёт' }));
  expect(await screen.findByText('Напиши отчёт по плану')).toBeInTheDocument();
  const navigation = within(screen.getByRole('group', { name: 'Вкладки чата' }));
  await user.click(navigation.getByRole('button', { name: 'План отчёта' }));
  expect(await panel.findByText('Подтверждён')).toBeInTheDocument();
  expect(panel.getByRole('button', { name: 'Изменить план' })).toBeDisabled();
}, 10000);

test('блокирует сохранение во время прогона и сохраняет правки при ошибке сервера', async () => {
  const user = await openEditablePlan();
  const note = screen.getByRole('textbox', { name: 'Заметка — Цель работы' });
  await user.clear(note);
  note.focus();
  await user.keyboard('Моя заметка');
  expect(note).toHaveValue('Моя заметка');
  const save = screen.getByRole('button', { name: 'Сохранить план' });
  act(() => emitMockEvent(demoId, { event: 'project.locked', data: { run_id: 'external' } }));
  await waitFor(() => expect(save).toBeDisabled());
  act(() => emitMockEvent(demoId, { event: 'project.unlocked', data: { run_id: 'external' } }));
  await waitFor(() => expect(save).toBeEnabled());
  server.use(
    http.put('/api/v1/projects/:pid/plan', () => invalid('sections.0.note', 'Уточните заметку')),
  );
  await user.click(save);
  expect(await screen.findByText('Уточните заметку')).toBeInTheDocument();
  expect(note).toHaveValue('Моя заметка');
}, 10000);
