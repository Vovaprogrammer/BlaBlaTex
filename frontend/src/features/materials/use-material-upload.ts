import { useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import type { components } from '@/api/schema';
import { uploadFetch, type UploadProgress } from '@/api/upload-fetch';
import { sessionKey, useSession } from '@/features/auth/use-session';
import { useDraftStore } from '@/features/editor/draft-context';
import { workspaceKeys } from '@/features/workspace/workspace-queries';

export const materialAccept =
  '.tex,.bib,.sty,.cls,.txt,.md,.csv,.py,.java,.c,.cpp,.h,.js,.ts,.sql,.go,.rs,.kt,.cs,.png,.jpg,.jpeg,.svg,.pdf,.docx,.pptx,.xlsx';
export function useMaterialUpload(project: string) {
  const client = useQueryClient();
  const drafts = useDraftStore();
  const { data: session } = useSession();
  const owner = session?.user.id;
  const controller = useRef<AbortController | null>(null);
  const [progress, setProgress] = useState<UploadProgress>({ percent: null, checking: false });
  const current = () =>
    Boolean(owner) &&
    client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id === owner;
  const mutation = useMutation({
    mutationKey: ['projects', project, 'upload'],
    meta: { sessionUserId: owner },
    mutationFn: async ({ files, dir }: { files: File[]; dir: string }) => {
      if (!current()) throw new DOMException('Сессия изменилась', 'AbortError');
      if (!files.length)
        throw new ApiError(422, 'validation_error', 'Выберите файлы для загрузки.');
      if (files.length > 100 || files.reduce((sum, file) => sum + file.size, 0) > 200 * 1024 ** 2)
        throw new ApiError(
          413,
          'payload_too_large',
          'За один раз можно загрузить до 100 файлов общим размером до 200 МБ.',
        );
      const large = files.find((file) => file.size > 20 * 1024 ** 2);
      if (large) throw new ApiError(413, 'payload_too_large', `Файл «${large.name}» больше 20 МБ.`);
      if (dir !== 'materials' && !dir.startsWith('materials/'))
        throw new ApiError(422, 'validation_error', 'Выберите папку в разделе «Материалы».');
      for (const file of files)
        drafts.assertCanChange(project, `${dir}/${file.name}`.normalize('NFC'));
      const form = new FormData();
      form.set('dir', dir);
      files.forEach((file) => form.append('files', file, file.name));
      const active = new AbortController();
      controller.current = active;
      setProgress({ percent: null, checking: false });
      const { data } = await api.POST('/api/v1/projects/{pid}/upload', {
        params: { path: { pid: project } },
        body: { files: files.map((file) => file.name), dir },
        bodySerializer: () => form,
        fetch: uploadFetch(form, (value) => {
          if (current() && !active.signal.aborted) setProgress(value);
        }),
        signal: active.signal,
      });
      if (!data) throw new ApiError(0, 'invalid_response', 'Сервер не подтвердил загрузку файлов.');
      return data;
    },
    onSuccess: async (data) => {
      if (!current()) return;
      await client.cancelQueries({ queryKey: workspaceKeys.tree(project), exact: true });
      if (!current()) return;
      for (const file of data.items) {
        void drafts.refresh(project, file.path, file.version);
        void client.invalidateQueries({
          queryKey: ['projects', project, 'material-text', file.path],
        });
      }
      await client.invalidateQueries({ queryKey: workspaceKeys.tree(project), exact: true });
    },
  });
  const reset = mutation.reset;
  useEffect(() => {
    reset();
    return () => {
      controller.current?.abort();
      controller.current = null;
    };
  }, [project, owner, reset]);
  return { ...mutation, progress };
}
export type MaterialUpload = ReturnType<typeof useMaterialUpload>;
