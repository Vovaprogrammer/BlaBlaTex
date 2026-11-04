import { http, HttpResponse } from 'msw';
import { newFile, ownedProject, type Schemas } from './data';
import { failure, guard, invalid, validPath } from './responses';
import { emitMockEvent } from './project-events';
import { materialText, prepareMaterialText } from './material-text';

export const materialHandlers = [
  http.get('/api/v1/projects/:pid/material-text', ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    const project = String(params.pid);
    const url = new URL(request.url);
    const path = url.searchParams.get('path') ?? '';
    const file = ownedProject(project)?.files.get(path);
    if (!file || file.info.role !== 'material' || file.info.kind === 'folder')
      return failure(404, 'not_found', 'Материал не найден');
    const data = materialText(project, path);
    const offset = Number(url.searchParams.get('offset') ?? 0);
    const limit = Number(url.searchParams.get('limit') ?? 20_000);
    return HttpResponse.json<Schemas['MaterialTextOut']>({
      ...data,
      offset,
      text: data.text?.slice(offset, offset + limit) ?? null,
    });
  }),
  http.post('/api/v1/projects/:pid/upload', async ({ request, params }) => {
    const denied = guard(request);
    if (denied) return denied;
    const project = ownedProject(String(params.pid));
    if (!project) return failure(404, 'not_found', 'Проект не найден');
    const form = await request.formData();
    const dir = String(form.get('dir') ?? '');
    const files = form.getAll('files').filter((file) => typeof file !== 'string');
    if (!files.length || files.length > 100) return invalid('files', 'Выберите от 1 до 100 файлов');
    const prepared: ReturnType<typeof newFile>[] = [];
    let version = Math.max(0, ...[...project.files.values()].map((file) => file.info.version));
    for (const file of files) {
      const path = (dir ? `${dir}/${file.name}` : file.name).normalize('NFC');
      if (!validPath(path)) return invalid('files', 'Недопустимое имя файла');
      const ext = path.split('.').at(-1)?.toLowerCase() ?? '';
      if (
        !'tex bib sty cls txt md csv py java c cpp h js ts sql go rs kt cs png jpg jpeg svg pdf docx pptx xlsx'
          .split(' ')
          .includes(ext)
      )
        return failure(
          415,
          'unsupported_file_type',
          `Формат файла «${file.name}» не поддерживается.`,
        );
      if (file.size > 20 * 1024 ** 2)
        return failure(413, 'payload_too_large', `Файл «${file.name}» больше 20 МБ.`);
      if (project.files.get(path)?.info.role === 'generated')
        return failure(403, 'forbidden', 'Файл создаётся автоматически');
      if (project.files.get(path)?.info.kind === 'folder')
        return failure(409, 'already_exists', 'На этом месте уже есть папка');
      const binary = ['png', 'jpg', 'jpeg', 'svg', 'pdf', 'docx', 'pptx', 'xlsx'].includes(ext);
      const mime =
        (
          {
            png: 'image/png',
            jpg: 'image/jpeg',
            jpeg: 'image/jpeg',
            svg: 'image/svg+xml',
            pdf: 'application/pdf',
          } as Record<string, string>
        )[ext] ?? (binary ? 'application/octet-stream' : 'text/plain');
      const blob = new Blob([await file.arrayBuffer()], { type: mime });
      const item = newFile(
        path,
        binary ? '' : await blob.text(),
        path.startsWith('materials/') ? 'material' : 'source',
      );
      item.info = {
        ...item.info,
        kind: binary ? 'binary' : 'text',
        mime,
        size: blob.size,
        version: ++version,
      };
      if (binary) item.blob = blob;
      prepared.push(item);
    }
    for (const item of prepared) {
      project.files.set(item.info.path, item);
      const parts = item.info.path.split('/');
      for (let i = 1; i < parts.length; i++) {
        const path = parts.slice(0, i).join('/');
        if (!project.files.has(path)) {
          const folder = newFile(path);
          folder.info.kind = 'folder';
          folder.info.mime = null;
          project.files.set(path, folder);
        }
      }
      emitMockEvent(String(params.pid), {
        event: 'file.changed',
        data: {
          path: item.info.path,
          version: item.info.version,
          author: 'user',
          changeset_id: null,
        },
      });
      if (item.info.role === 'material') prepareMaterialText(String(params.pid), item.info.path);
    }
    return HttpResponse.json<Schemas['UploadResult']>({ items: prepared.map((file) => file.info) });
  }),
];
