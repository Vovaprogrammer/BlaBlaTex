import { http, HttpResponse } from 'msw/http';
import { newFile, ownedProject } from './data';
import type { Schemas } from './data';
import { failure, guard, invalid, readBody, validPath } from './responses';
import { emitMockEvent } from './project-events';
import { prepareMaterialText } from './material-text';

const fileRoute = /\/api\/v1\/projects\/([^/]+)\/files\/(.+)$/;
function filePath(request: Request) {
  const pathname = new URL(request.url).pathname;
  return decodeURIComponent(pathname.slice(pathname.indexOf('/files/') + 7)).normalize('NFC');
}
function touches(path: string, file: string) {
  return file === path || file.startsWith(path + '/');
}

export const fileHandlers = [
  http.get('/api/v1/projects/:pid/tree', ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    const value = ownedProject(String(params.pid));
    if (!value) return failure(404, 'not_found', 'Проект не найден');
    return HttpResponse.json<Schemas['FileTree']>({
      items: [...value.files.values()].map((item) => item.info),
    });
  }),
  http.get(fileRoute, ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    const path = filePath(request);
    if (!validPath(path)) return invalid('path', 'Недопустимое имя файла');
    const file = ownedProject(String(params[0]))?.files.get(path);
    if (!file || file.info.kind === 'folder') return failure(404, 'not_found', 'Файл не найден');
    if (file.blob)
      return new HttpResponse(file.blob, {
        headers: {
          ETag: `"${file.info.version}"`,
          'Content-Type': file.info.mime ?? 'application/octet-stream',
        },
      });
    return HttpResponse.text(file.text, {
      headers: { ETag: `"${file.info.version}"`, 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }),
  http.put(fileRoute, async ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    const value = ownedProject(String(params[0]));
    if (!value) return failure(404, 'not_found', 'Проект не найден');
    const path = filePath(request);
    if (!validPath(path)) return invalid('path', 'Недопустимое имя файла');
    const previous = value.files.get(path);
    if (previous?.info.role === 'generated')
      return failure(403, 'forbidden', 'Файл создаётся автоматически');
    if (previous?.info.kind === 'folder')
      return failure(409, 'already_exists', 'Папка уже существует');
    if (previous && request.headers.get('If-None-Match') === '*')
      return failure(409, 'already_exists', 'Файл уже существует');
    const expected = request.headers.get('If-Match');
    if (expected && expected !== `"${previous?.info.version}"`)
      return failure(412, 'file_conflict', 'Файл изменён в другом месте', {
        current_version: previous?.info.version ?? 0,
      });
    const text = await request.text();
    if (new TextEncoder().encode(text).length > 2 * 1024 * 1024)
      return failure(413, 'payload_too_large', 'Текстовый файл должен быть не больше 2 МБ');
    if (!/\.(tex|bib|sty|cls|txt|md|csv|py|java|c|cpp|h|js|ts|sql|go|rs|kt|cs)$/i.test(path))
      return failure(415, 'unsupported_file_type', 'Этот тип текстового файла не поддерживается');
    const file = newFile(path, text, path.startsWith('materials/') ? 'material' : 'source');
    file.info.version = (previous?.info.version ?? 0) + 1;
    value.files.set(path, file);
    const parts = path.split('/');
    for (let i = 1; i < parts.length; i++) {
      const folder = parts.slice(0, i).join('/');
      if (!value.files.has(folder)) {
        const item = newFile(folder);
        item.info.kind = 'folder';
        item.info.mime = null;
        value.files.set(folder, item);
      }
    }
    emitMockEvent(String(params[0]), {
      event: 'file.changed',
      data: { path, version: file.info.version, author: 'user', changeset_id: null },
    });
    if (file.info.role === 'material') prepareMaterialText(String(params[0]), path);
    return HttpResponse.json<Schemas['FileInfo']>(file.info, { status: previous ? 200 : 201 });
  }),
  http.delete(fileRoute, ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    const value = ownedProject(String(params[0]));
    const path = filePath(request);
    if (!value || !value.files.has(path)) return failure(404, 'not_found', 'Файл не найден');
    if (
      [...value.files.values()].some(
        (item) => touches(path, item.info.path) && item.info.role === 'generated',
      )
    )
      return failure(403, 'forbidden', 'Файл создаётся автоматически');
    for (const key of value.files.keys()) if (touches(path, key)) value.files.delete(key);
    emitMockEvent(String(params[0]), { event: 'file.deleted', data: { path, changeset_id: null } });
    return new HttpResponse(null, { status: 204 });
  }),
  http.post('/api/v1/projects/:pid/folders', async ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    const value = ownedProject(String(params.pid));
    if (!value) return failure(404, 'not_found', 'Проект не найден');
    const body = await readBody(request);
    if (typeof body.path !== 'string' || !validPath(body.path))
      return invalid('path', 'Недопустимое имя папки');
    if (value.files.has(body.path)) return failure(409, 'already_exists', 'Путь уже существует');
    const folder = newFile(body.path);
    folder.info.kind = 'folder';
    folder.info.mime = null;
    value.files.set(body.path, folder);
    emitMockEvent(String(params.pid), {
      event: 'file.changed',
      data: { path: body.path, version: folder.info.version, author: 'user', changeset_id: null },
    });
    return HttpResponse.json<Schemas['FileInfo']>(folder.info, { status: 201 });
  }),
  http.post('/api/v1/projects/:pid/move', async ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    const value = ownedProject(String(params.pid));
    if (!value) return failure(404, 'not_found', 'Проект не найден');
    const body = await readBody(request);
    if (
      typeof body.from !== 'string' ||
      typeof body.to !== 'string' ||
      !validPath(body.from) ||
      !validPath(body.to) ||
      body.to.startsWith(body.from + '/')
    )
      return invalid('to', 'Недопустимый путь');
    if (!value.files.has(body.from)) return failure(404, 'not_found', 'Файл не найден');
    if (
      [...value.files.values()].some(
        (item) => touches(String(body.from), item.info.path) && item.info.role === 'generated',
      )
    )
      return failure(403, 'forbidden', 'Файл создаётся автоматически');
    if (value.files.has(body.to)) return failure(409, 'already_exists', 'Путь уже существует');
    for (const [path, file] of [...value.files.entries()])
      if (touches(body.from, path)) {
        value.files.delete(path);
        const target = body.to + path.slice(body.from.length);
        file.info.path = target;
        if (file.info.kind !== 'folder')
          file.info.role = target.startsWith('materials/') ? 'material' : 'source';
        value.files.set(target, file);
        if (file.info.role === 'material') prepareMaterialText(String(params.pid), target);
      }
    emitMockEvent(String(params.pid), {
      event: 'file.moved',
      data: { from: body.from, to: body.to, changeset_id: null },
    });
    return HttpResponse.json<Schemas['FileInfo']>(value.files.get(body.to)!.info);
  }),
];
