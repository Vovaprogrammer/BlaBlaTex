export type UploadProgress = { percent: number | null; checking: boolean };

// Транспорт для сгенерированного клиента: fetch не сообщает прогресс отправки тела.
export function uploadFetch(form: FormData, progress: (value: UploadProgress) => void) {
  return (request: Request): Promise<Response> =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const abort = () => xhr.abort();
      const finish = () => request.signal.removeEventListener('abort', abort);
      xhr.open(request.method, request.url);
      xhr.withCredentials = request.credentials === 'include';
      xhr.responseType = 'arraybuffer';
      // XHR создаёт собственную границу multipart при send(FormData).
      request.headers.forEach((value, name) => {
        if (name.toLowerCase() !== 'content-type') xhr.setRequestHeader(name, value);
      });
      xhr.upload.onprogress = (event) =>
        progress({
          percent: event.lengthComputable ? Math.round((event.loaded / event.total) * 100) : null,
          checking: event.lengthComputable && event.loaded === event.total,
        });
      xhr.upload.onload = () => progress({ percent: 100, checking: true });
      xhr.onload = () => {
        finish();
        const headers = new Headers();
        for (const line of xhr
          .getAllResponseHeaders()
          .trim()
          .split(/[\r\n]+/)) {
          const colon = line.indexOf(':');
          if (colon > 0) headers.append(line.slice(0, colon), line.slice(colon + 1).trim());
        }
        resolve(new Response(xhr.response as ArrayBuffer, { status: xhr.status, headers }));
      };
      xhr.onerror = () => {
        finish();
        reject(new TypeError('Не удалось передать файлы'));
      };
      xhr.onabort = () => {
        finish();
        reject(new DOMException('Загрузка отменена', 'AbortError'));
      };
      if (request.signal.aborted) {
        reject(new DOMException('Загрузка отменена', 'AbortError'));
        return;
      }
      request.signal.addEventListener('abort', abort, { once: true });
      try {
        xhr.send(form);
      } catch (error) {
        finish();
        reject(error);
      }
    });
}
