import { useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import { ApiError } from '@/api/api-error';
import type { components } from '@/api/schema';
import { sessionKey, useSession } from '@/features/auth/use-session';
import type { MaterialUpload } from '@/features/materials/use-material-upload';
import { usageKey } from '@/features/settings/usage-query';
import { chatKey, postChatMessage, type Run } from './chat-data';

const maxLength = 10_000;
export function isQuotaExceeded(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 429 && error.code === 'quota_exceeded';
}

const messagesBody = (text: string, paths: string[]) =>
  [text.trim(), paths.length ? ['Материалы:', ...paths.map((path) => '• ' + path)].join('\n') : '']
    .filter(Boolean)
    .join('\n\n');

export function useChatActions(id: string, upload: MaterialUpload, refresh: () => void) {
  const client = useQueryClient();
  const { data: session } = useSession();
  const owner = session?.user.id;
  const current = () =>
    Boolean(owner) &&
    client.getQueryData<components['schemas']['MeResponse'] | null>(sessionKey)?.user.id === owner;
  const [text, setText] = useState('');
  const [paths, setPaths] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<unknown>();
  const [stopping, setStopping] = useState<string>();
  const attaching = useRef(false);
  const submitLock = useRef(false);
  const payload = messagesBody(text, paths);
  const tooLong = Array.from(payload).length > maxLength;
  const send = useMutation({
    meta: { sessionUserId: owner },
    mutationFn: async (body: string) => {
      if (!current()) throw new DOMException('Сессия изменилась', 'AbortError');
      return postChatMessage(id, body);
    },
    onSuccess(data) {
      if (!current()) return;
      client.setQueryData<components['schemas']['MessageList']>(chatKey(id), (old) => {
        if (!old) return old;
        const items = old.items.some((message) => message.id === data.message.id)
          ? old.items
          : [...old.items, data.message];
        const answered = old.items.find((item) => item.id === data.run.message_id);
        return {
          ...old,
          items,
          active_run: old.active_run ?? (answered ? null : data.run),
        };
      });
      setText('');
      setPaths([]);
      refresh();
    },
    onError(error) {
      if (!current()) return;
      if (error instanceof ApiError && error.status === 423) refresh();
      if (isQuotaExceeded(error)) void client.invalidateQueries({ queryKey: usageKey });
    },
  });
  const cancel = useMutation({
    meta: { sessionUserId: owner },
    mutationFn: async (runId: string) => {
      if (!current()) throw new DOMException('Сессия изменилась', 'AbortError');
      const { data } = await api.POST('/api/v1/runs/{rid}/cancel', {
        params: { path: { rid: runId } },
      });
      if (!data) throw new ApiError(0, 'invalid_response', 'Сервер не подтвердил остановку.');
      return data;
    },
    onSuccess(data) {
      if (!current()) return;
      refresh();
      if (data.status === 'running' || data.status === 'queued') setStopping(data.id);
    },
  });
  async function attach(files: File[]) {
    if (!files.length || upload.isPending || attaching.current || submitLock.current) return;
    attaching.current = true;
    setUploading(true);
    setUploadError(undefined);
    try {
      const data = await upload.mutateAsync({ files, dir: 'materials' });
      if (current())
        setPaths((old) => [...new Set([...old, ...data.items.map((item) => item.path)])]);
    } catch (error) {
      if (current() && !(error instanceof DOMException && error.name === 'AbortError'))
        setUploadError(error);
    } finally {
      attaching.current = false;
      setUploading(false);
    }
  }
  async function submit(active: Run | null) {
    if (!payload || tooLong || active || submitLock.current || attaching.current) return;
    submitLock.current = true;
    try {
      await send.mutateAsync(payload);
    } catch {
      // Текст остаётся в поле, ошибка показывается рядом.
    } finally {
      submitLock.current = false;
    }
  }
  return {
    text,
    setText,
    paths,
    remove: (path: string) => setPaths((old) => old.filter((item) => item !== path)),
    upload,
    attach,
    uploading,
    uploadError,
    send,
    submit,
    cancel,
    stopping,
    tooLong,
  };
}

export type ChatActions = ReturnType<typeof useChatActions>;
