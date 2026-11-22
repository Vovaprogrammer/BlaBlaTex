import { act, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test } from 'vitest';
import { demoId, newFile, ownedProject } from '@/mocks/data';
import { emitMockEvent } from '@/mocks/project-events';
import { renderApp } from '@/test/render-app';

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
