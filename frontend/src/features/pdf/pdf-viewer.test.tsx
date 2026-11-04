import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test } from 'vitest';
import { PdfViewer } from './pdf-viewer';
import { initialPdfPosition } from './pdf-position';

test('просмотрщик листает страницы, меняет масштаб и восстанавливает настройки после открытия', async () => {
  const position = initialPdfPosition();
  const blob = new Blob(['PDF']);
  const app = render(<PdfViewer blob={blob} position={position} />);
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Следующая страница' })).toBeEnabled(),
  );
  await userEvent.setup().click(screen.getByRole('button', { name: 'Следующая страница' }));
  expect(position.get().page).toBe(2);
  await userEvent
    .setup()
    .selectOptions(screen.getByRole('combobox', { name: 'Масштаб PDF' }), '1.5');
  expect(position.get().zoom).toBe(1.5);
  app.unmount();
  render(<PdfViewer blob={blob} position={position} />);
  expect(screen.getByRole('spinbutton', { name: 'Номер страницы PDF' })).toHaveValue(2);
  expect(screen.getByRole('combobox', { name: 'Масштаб PDF' })).toHaveValue('1.5');
});
