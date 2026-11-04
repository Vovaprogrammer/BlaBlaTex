import { afterEach, expect, test, vi } from 'vitest';
import { uploadFetch } from './upload-fetch';

class Transport {
  static current: Transport;
  constructor() {
    Transport.current = this;
  }
  open = vi.fn();
  send = vi.fn();
  setRequestHeader = vi.fn();
  withCredentials = false;
  responseType = '';
  status = 200;
  response = new TextEncoder().encode('{"items":[]}').buffer;
  getAllResponseHeaders = () => 'Content-Type: application/json\r\nX-Test: ok';
  upload: { onprogress?: (event: ProgressEvent) => void; onload?: () => void } = {};
  onload?: () => void;
  onabort?: () => void;
  onerror?: () => void;
  abort = () => this.onabort?.();
}
afterEach(() => vi.unstubAllGlobals());

test('транспорт передаёт cookies и CSRF, сообщает прогресс, оставляет границу multipart браузеру', async () => {
  vi.stubGlobal('XMLHttpRequest', Transport);
  const progress = vi.fn();
  const form = new FormData();
  const promise = uploadFetch(
    form,
    progress,
  )(
    new Request('http://localhost/upload', {
      method: 'POST',
      credentials: 'include',
      headers: { 'X-CSRF-Protection': '1', 'Content-Type': 'multipart/form-data; boundary=old' },
    }),
  );
  const xhr = Transport.current;
  expect(xhr.withCredentials).toBe(true);
  expect(xhr.setRequestHeader.mock.calls).toEqual([['x-csrf-protection', '1']]);
  expect(xhr.send).toHaveBeenCalledWith(form);
  xhr.upload.onprogress?.(
    new ProgressEvent('progress', { lengthComputable: true, loaded: 25, total: 100 }),
  );
  expect(progress).toHaveBeenLastCalledWith({ percent: 25, checking: false });
  xhr.upload.onload?.();
  expect(progress).toHaveBeenLastCalledWith({ percent: 100, checking: true });
  xhr.onload?.();
  const response = await promise;
  expect(response.headers.get('X-Test')).toBe('ok');
  expect(await response.json()).toEqual({ items: [] });
});

test('смена проекта отменяет передачу через AbortSignal', async () => {
  vi.stubGlobal('XMLHttpRequest', Transport);
  const controller = new AbortController();
  const promise = uploadFetch(
    new FormData(),
    vi.fn(),
  )(new Request('http://localhost/upload', { method: 'POST', signal: controller.signal }));
  controller.abort();
  await expect(promise).rejects.toMatchObject({ name: 'AbortError' });
});
