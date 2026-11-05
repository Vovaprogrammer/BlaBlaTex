import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { ApiError } from '@/api/api-error';
import { DraftStore } from './draft-store';

const stores: DraftStore[] = [];
beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  stores.splice(0).forEach((store) => store.pause());
  vi.useRealTimers();
});
async function setup() {
  const load = vi.fn(async () => ({ text: 'Версия 1', etag: '"1"' }));
  const save = vi.fn(async () => '"2"');
  const store = new DraftStore({ load, save });
  stores.push(store);
  store.open('project', 'main.tex', false);
  await Promise.resolve();
  return { store, load, save };
}
const edit = (store: DraftStore, text: string) => store.edit('project', 'main.tex', text);
const draft = (store: DraftStore) => store.get('project', 'main.tex')!;

test('отказ 423 сохраняет черновик и не повторяет запись до разблокировки', async () => {
  const { store, save } = await setup();
  save.mockRejectedValueOnce(
    new ApiError(423, 'project_locked', 'Проект занят', { run_id: 'run' }),
  );
  edit(store, 'Моя правка');
  await vi.advanceTimersByTimeAsync(1500);
  expect(store.projectLock('project')?.runId).toBe('run');
  expect(draft(store).text).toBe('Моя правка');
  edit(store, 'Попытка изменить текст во время блокировки');
  await expect(store.flush('project')).rejects.toMatchObject({ code: 'unsaved_changes' });
  await vi.advanceTimersByTimeAsync(3000);
  expect(save).toHaveBeenCalledTimes(1);
  store.setProjectLock('project', null);
  await vi.advanceTimersByTimeAsync(1500);
  expect(draft(store)).toMatchObject({ text: 'Моя правка', status: 'saved' });
});

test('после снятия блокировки правки агента сравниваются с локальным черновиком', async () => {
  const { store, load, save } = await setup();
  edit(store, 'Моя правка');
  store.setProjectLock('project', 'run');
  await vi.advanceTimersByTimeAsync(2000);
  expect(save).not.toHaveBeenCalled();
  load.mockResolvedValue({ text: 'Версия агента', etag: '"2"' });
  store.setProjectLock('project', null);
  await vi.advanceTimersByTimeAsync(2000);
  expect(draft(store)).toMatchObject({
    text: 'Моя правка',
    status: 'conflict',
    remote: { text: 'Версия агента', etag: '"2"' },
  });
  expect(save).not.toHaveBeenCalled();
});

test('внешнее событие обновляет сохранённый файл и игнорирует старую версию', async () => {
  const { store, load } = await setup();
  load.mockResolvedValue({ text: 'Внешний текст', etag: '"3"' });
  await store.refresh('project', 'main.tex', 3);
  expect(draft(store)).toMatchObject({ text: 'Внешний текст', status: 'saved', etag: '"3"' });
  await store.refresh('project', 'main.tex', 2);
  expect(load).toHaveBeenCalledTimes(2);
});

test('переподключение во время повторного открытия той же версии завершает загрузку', async () => {
  const { store, load } = await setup();
  load.mockImplementationOnce(() => new Promise(() => {}));
  store.open('project', 'main.tex', false);
  expect(draft(store).status).toBe('loading');
  await store.refresh('project', 'main.tex');
  expect(draft(store)).toMatchObject({ status: 'saved', text: 'Версия 1' });
});

test('SSE до ответа собственной записи не создаёт ложный конфликт', async () => {
  const { store, load, save } = await setup();
  let finish!: (etag: string) => void;
  save.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  edit(store, 'Моя запись');
  await vi.advanceTimersByTimeAsync(1500);
  await store.refresh('project', 'main.tex', 2);
  edit(store, 'Следующий ввод');
  finish('"2"');
  await vi.advanceTimersByTimeAsync(0);
  expect(draft(store)).toMatchObject({ text: 'Следующий ввод', status: 'dirty', etag: '"2"' });
  expect(load).toHaveBeenCalledTimes(1);
});

test('правка сервера во время PUT сравнивается после ответа, новый ввод сохраняется', async () => {
  const { store, load, save } = await setup();
  let finish!: (etag: string) => void;
  save.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  edit(store, 'Первая запись');
  await vi.advanceTimersByTimeAsync(1500);
  edit(store, 'Последний ввод');
  load.mockResolvedValue({ text: 'Внешняя версия', etag: '"3"' });
  await store.refresh('project', 'main.tex', 3);
  finish('"2"');
  await vi.advanceTimersByTimeAsync(0);
  expect(draft(store)).toMatchObject({
    text: 'Последний ввод',
    status: 'conflict',
    remote: { text: 'Внешняя версия', etag: '"3"' },
  });
  await vi.advanceTimersByTimeAsync(5000);
  expect(save).toHaveBeenCalledTimes(1);
});

test('ввод во время получения внешней версии не записывается поверх неё', async () => {
  const { store, load, save } = await setup();
  let finish!: (value: { text: string; etag: string }) => void;
  load.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const refresh = store.refresh('project', 'main.tex', 2);
  edit(store, 'Мой ввод во время запроса');
  await vi.advanceTimersByTimeAsync(2000);
  expect(save).not.toHaveBeenCalled();
  finish({ text: 'Внешняя версия', etag: '"2"' });
  await refresh;
  expect(draft(store)).toMatchObject({ text: 'Мой ввод во время запроса', status: 'conflict' });
});

test('переподключение с той же версией сохраняет черновик без конфликта', async () => {
  const { store, save } = await setup();
  edit(store, 'Мой ввод');
  await store.refresh('project', 'main.tex');
  expect(draft(store).status).toBe('dirty');
  await vi.advanceTimersByTimeAsync(1500);
  expect(save).toHaveBeenCalledTimes(1);
});

test('внешнее удаление прекращает запись и сохраняет несохранённый текст', async () => {
  const { store, save } = await setup();
  edit(store, 'Не потерять');
  store.removedExternally('project', 'main.tex');
  await vi.advanceTimersByTimeAsync(5000);
  expect(save).not.toHaveBeenCalled();
  expect(draft(store)).toMatchObject({ text: 'Не потерять', status: 'missing' });
  expect(store.pending()).toHaveLength(1);
});

test('удалённый чистый файл не возвращается из запоздавшего GET', async () => {
  const { store, load } = await setup();
  let finish!: (value: { text: string; etag: string }) => void;
  load.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const refresh = store.refresh('project', 'main.tex', 2);
  store.removedExternally('project', 'main.tex');
  finish({ text: 'Запоздавший текст', etag: '"2"' });
  await refresh;
  expect(store.get('project', 'main.tex')).toBeUndefined();
});

test('удаление проекта очищает сохранённые файлы, но защищает несохранённый текст', async () => {
  const { store } = await setup();
  edit(store, 'Мой текст');
  expect(() => store.removeProject('project')).toThrow('Сначала сохраните');
  await vi.advanceTimersByTimeAsync(1500);
  store.removeProject('project');
  expect(store.get('project', 'main.tex')).toBeUndefined();
});

test('сохранение перед сборкой ждёт запись и новый ввод во время неё', async () => {
  const { store, save } = await setup();
  let finish!: (etag: string) => void;
  save.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  edit(store, 'Первая версия');
  const flushed = store.flush('project');
  edit(store, 'Последняя версия');
  finish('"2"');
  await flushed;
  expect(draft(store)).toMatchObject({ text: 'Последняя версия', status: 'saved' });
  expect(save).toHaveBeenCalledTimes(2);
});

test('последний ввод сохраняется через 1,5 секунды с исходной версией', async () => {
  const { store, save } = await setup();
  edit(store, 'Первая правка');
  await vi.advanceTimersByTimeAsync(1000);
  edit(store, 'Последняя правка');
  await vi.advanceTimersByTimeAsync(1499);
  expect(save).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(1);
  expect(save.mock.calls[0]?.slice(0, 4)).toEqual([
    'project',
    'main.tex',
    'Последняя правка',
    '"1"',
  ]);
  expect(draft(store)).toMatchObject({ status: 'saved', text: 'Последняя правка', etag: '"2"' });
});

test('ввод во время записи не теряется и следующий запрос использует новую версию', async () => {
  const { store, save } = await setup();
  let finish!: (etag: string) => void;
  save.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  edit(store, 'Правка А');
  await vi.advanceTimersByTimeAsync(1500);
  edit(store, 'Правка Б');
  await vi.advanceTimersByTimeAsync(1500);
  expect(save).toHaveBeenCalledTimes(1);
  finish('"2"');
  await vi.advanceTimersByTimeAsync(0);
  expect(draft(store)).toMatchObject({ text: 'Правка Б', base: 'Правка А', status: 'dirty' });
  await vi.advanceTimersByTimeAsync(1500);
  expect(save.mock.calls[1]?.slice(0, 4)).toEqual(['project', 'main.tex', 'Правка Б', '"2"']);
  expect(draft(store).status).toBe('saved');
});

test('ошибка записи сохраняет черновик и не запускает бесконечные повторы', async () => {
  const { store, save } = await setup();
  save.mockRejectedValueOnce(new ApiError(500, 'internal', 'Попробуйте позже'));
  edit(store, 'Не терять');
  await vi.advanceTimersByTimeAsync(1500);
  expect(draft(store)).toMatchObject({
    status: 'error',
    text: 'Не терять',
    error: 'Попробуйте позже',
  });
  await vi.advanceTimersByTimeAsync(10_000);
  expect(save).toHaveBeenCalledTimes(1);
  store.retry('project', 'main.tex');
  await vi.advanceTimersByTimeAsync(0);
  expect(draft(store)).toMatchObject({ status: 'saved', text: 'Не терять' });
});

test('412 останавливает запись, сравнивает свежий серверный текст и сохраняет мой с новой версией', async () => {
  const { store, load, save } = await setup();
  save.mockRejectedValueOnce(new ApiError(412, 'file_conflict', 'Файл изменился'));
  load.mockResolvedValueOnce({ text: 'Чужая правка', etag: '"7"' });
  edit(store, 'Мой текст');
  await vi.advanceTimersByTimeAsync(1500);
  expect(draft(store)).toMatchObject({
    status: 'conflict',
    text: 'Мой текст',
    remote: { text: 'Чужая правка', etag: '"7"' },
  });
  await vi.advanceTimersByTimeAsync(5000);
  expect(save).toHaveBeenCalledTimes(1);
  store.resolve('project', 'main.tex', 'mine');
  await vi.advanceTimersByTimeAsync(0);
  expect(save.mock.calls[1]?.slice(0, 4)).toEqual(['project', 'main.tex', 'Мой текст', '"7"']);
});

test('повторный конфликт не перезаписывает изменения; серверный выбор сохраняет копию моего текста', async () => {
  const { store, load, save } = await setup();
  save.mockRejectedValueOnce(new ApiError(412, 'file_conflict', 'Конфликт'));
  load.mockResolvedValueOnce({ text: 'Сервер 2', etag: '"2"' });
  edit(store, 'Мой текст');
  await vi.advanceTimersByTimeAsync(1500);
  save.mockRejectedValueOnce(new ApiError(412, 'file_conflict', 'Ещё один конфликт'));
  load.mockResolvedValueOnce({ text: 'Сервер 3', etag: '"3"' });
  store.resolve('project', 'main.tex', 'mine');
  await vi.advanceTimersByTimeAsync(0);
  expect(draft(store)).toMatchObject({
    status: 'conflict',
    text: 'Мой текст',
    remote: { etag: '"3"' },
  });
  store.resolve('project', 'main.tex', 'server');
  expect(draft(store)).toMatchObject({ text: 'Сервер 3', backup: 'Мой текст', status: 'saved' });
  store.restore('project', 'main.tex');
  expect(draft(store).text).toBe('Мой текст');
});

test('удаление файла на сервере сохраняет локальный текст для восстановления', async () => {
  const { store, load, save } = await setup();
  save.mockRejectedValueOnce(new ApiError(412, 'file_conflict', 'Файл удалён'));
  load.mockRejectedValueOnce(new ApiError(404, 'not_found', 'Файл не найден'));
  edit(store, 'Важный текст');
  await vi.advanceTimersByTimeAsync(1500);
  expect(draft(store)).toMatchObject({ status: 'missing', text: 'Важный текст' });
  expect(store.pending()).toHaveLength(1);
});

test('возврат в сессию возобновляет прерванное чтение конфликтующей версии', async () => {
  const { store, load, save } = await setup();
  save.mockRejectedValueOnce(new ApiError(412, 'file_conflict', 'Файл изменился'));
  load.mockImplementationOnce(() => new Promise(() => {}));
  edit(store, 'Мой текст');
  await vi.advanceTimersByTimeAsync(1500);
  expect(draft(store).status).toBe('conflict');
  store.pause();
  load.mockResolvedValueOnce({ text: 'Новая версия', etag: '"7"' });
  store.resume();
  await vi.advanceTimersByTimeAsync(0);
  expect(draft(store)).toMatchObject({
    text: 'Мой текст',
    remote: { text: 'Новая версия', etag: '"7"' },
  });
});

test('выход останавливает таймеры, возвращение возобновляет сохранение черновика', async () => {
  const { store, save } = await setup();
  edit(store, 'Черновик');
  store.pause();
  await vi.advanceTimersByTimeAsync(5000);
  expect(save).not.toHaveBeenCalled();
  expect(draft(store).text).toBe('Черновик');
  store.resume();
  await vi.advanceTimersByTimeAsync(1500);
  expect(save).toHaveBeenCalledTimes(1);
});

test('автоматический файл не изменяется и не отправляется на сохранение', async () => {
  const { store, save } = await setup();
  store.open('project', 'meta.tex', true);
  await Promise.resolve();
  store.edit('project', 'meta.tex', 'Нельзя');
  await vi.advanceTimersByTimeAsync(1500);
  expect(store.get('project', 'meta.tex')?.text).toBe('Версия 1');
  expect(save).not.toHaveBeenCalled();
});

test('папку с несохранённым файлом нельзя удалить или перенести', async () => {
  const { store } = await setup();
  edit(store, 'Черновик');
  expect(() => store.assertCanChange('project', 'main.tex')).toThrow('Сначала сохраните изменения');
  expect(() => store.assertCanChange('project', 'другой.tex')).not.toThrow();
});
