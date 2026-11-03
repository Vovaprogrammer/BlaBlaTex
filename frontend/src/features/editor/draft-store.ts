import { ApiError } from '@/api/api-error';
import { errorMessage } from '@/app/query-client';

export type FileText = { text: string; etag: string };
export type Draft = {
  project: string;
  path: string;
  text: string;
  base: string;
  etag: string;
  readOnly: boolean;
  status: 'loading' | 'saved' | 'dirty' | 'saving' | 'error' | 'conflict' | 'locked' | 'missing';
  error?: string;
  remote?: FileText;
  backup?: string;
};
export type DraftServices = {
  load: (project: string, path: string, signal: AbortSignal) => Promise<FileText>;
  save: (
    project: string,
    path: string,
    text: string,
    etag: string,
    signal: AbortSignal,
  ) => Promise<string>;
};
const keyOf = (project: string, path: string) => JSON.stringify([project, path]);
const inside = (path: string, parent: string) => path === parent || path.startsWith(parent + '/');
export const hasDraftChanges = (draft: Draft) =>
  !draft.readOnly &&
  (draft.text !== draft.base ||
    ['dirty', 'saving', 'conflict'].includes(draft.status) ||
    (draft.status === 'missing' && Boolean(draft.etag)));

// Черновики живут только в памяти. Ни токены, ни текст файлов не пишутся в localStorage.
export class DraftStore {
  private entries = new Map<string, Draft>();
  private listeners = new Set<() => void>();
  private timers = new Map<string, ReturnType<typeof setTimeout>>();
  private saves = new Map<string, AbortController>();
  private loads = new Map<string, AbortController>();
  private active = true;
  private revision = 0;
  constructor(private services: DraftServices) {}
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  snapshot = () => this.revision;
  get = (project: string, path: string) => this.entries.get(keyOf(project, path));
  all = () => [...this.entries.values()];
  pending = () => this.all().filter(hasDraftChanges);
  private set(key: string, draft: Draft) {
    this.entries.set(key, draft);
    this.revision++;
    for (const listener of this.listeners) listener();
  }
  private patch(key: string, update: Partial<Draft>) {
    const draft = this.entries.get(key);
    if (draft) this.set(key, { ...draft, ...update });
  }
  private cancelTimer(key: string) {
    clearTimeout(this.timers.get(key));
    this.timers.delete(key);
  }
  private schedule(key: string) {
    this.cancelTimer(key);
    if (!this.active || this.saves.has(key) || this.entries.get(key)?.status !== 'dirty') return;
    this.timers.set(
      key,
      setTimeout(() => {
        this.timers.delete(key);
        void this.save(key);
      }, 1500),
    );
  }
  open(project: string, path: string, readOnly: boolean, version?: number) {
    const key = keyOf(project, path);
    const old = this.entries.get(key);
    if (!old)
      this.set(key, { project, path, text: '', base: '', etag: '', readOnly, status: 'loading' });
    else if (hasDraftChanges(old) || (version !== undefined && old.etag === `"${version}"`)) return;
    else if (!this.loads.has(key)) this.patch(key, { status: 'loading' });
    if (!this.loads.has(key) && this.active) void this.load(key);
  }
  private async load(key: string, conflict = false) {
    const draft = this.entries.get(key);
    if (!draft || !this.active) return;
    this.loads.get(key)?.abort();
    const controller = new AbortController();
    this.loads.set(key, controller);
    try {
      const remote = await this.services.load(draft.project, draft.path, controller.signal);
      if (controller.signal.aborted || this.loads.get(key) !== controller) return;
      if (conflict) this.patch(key, { status: 'conflict', remote, error: undefined });
      else if (!hasDraftChanges(this.entries.get(key) ?? draft))
        this.patch(key, {
          text: remote.text,
          base: remote.text,
          etag: remote.etag,
          status: 'saved',
          error: undefined,
        });
    } catch (error) {
      if (!controller.signal.aborted)
        this.patch(key, {
          status:
            error instanceof ApiError && error.status === 404
              ? 'missing'
              : conflict
                ? 'conflict'
                : 'error',
          error: errorMessage(error),
        });
    } finally {
      if (this.loads.get(key) === controller) this.loads.delete(key);
    }
  }
  edit(project: string, path: string, text: string) {
    const key = keyOf(project, path);
    const draft = this.entries.get(key);
    if (
      !draft ||
      draft.readOnly ||
      !draft.etag ||
      ['loading', 'conflict', 'locked', 'missing'].includes(draft.status)
    )
      return;
    this.patch(key, {
      text,
      status: this.saves.has(key) ? 'saving' : text === draft.base ? 'saved' : 'dirty',
      error: undefined,
    });
    this.schedule(key);
  }
  private async save(key: string) {
    this.cancelTimer(key);
    const draft = this.entries.get(key);
    if (
      !draft ||
      !this.active ||
      draft.readOnly ||
      !draft.etag ||
      this.saves.has(key) ||
      draft.status !== 'dirty'
    )
      return;
    const controller = new AbortController();
    this.saves.set(key, controller);
    this.patch(key, { status: 'saving', error: undefined });
    try {
      const etag = await this.services.save(
        draft.project,
        draft.path,
        draft.text,
        draft.etag,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      const current = this.entries.get(key);
      if (current)
        this.patch(key, {
          base: draft.text,
          etag,
          status: current.text === draft.text ? 'saved' : 'dirty',
          remote: undefined,
          error: undefined,
        });
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.status === 412) {
        this.patch(key, { status: 'conflict', error: undefined, remote: undefined });
        await this.load(key, true);
      } else
        this.patch(key, {
          status:
            error instanceof ApiError && error.status === 404
              ? 'missing'
              : error instanceof ApiError && [403, 423].includes(error.status)
                ? 'locked'
                : 'error',
          error: errorMessage(error),
        });
    } finally {
      if (this.saves.get(key) === controller) this.saves.delete(key);
      this.schedule(key);
    }
  }
  retry(project: string, path: string) {
    const key = keyOf(project, path);
    const draft = this.entries.get(key);
    if (!draft) return;
    if (draft.status === 'conflict') {
      void this.load(key, true);
      return;
    }
    if (!draft.etag || draft.status === 'missing') {
      if (!draft.etag) void this.load(key);
      else {
        this.patch(key, { status: 'conflict' });
        void this.load(key, true);
      }
      return;
    }
    this.patch(key, { status: 'dirty', error: undefined });
    void this.save(key);
  }
  resolve(project: string, path: string, choice: 'server' | 'mine') {
    const key = keyOf(project, path);
    const draft = this.entries.get(key);
    if (!draft?.remote) return;
    const remote = draft.remote;
    this.patch(key, {
      base: remote.text,
      etag: remote.etag,
      text: choice === 'server' ? remote.text : draft.text,
      backup: choice === 'server' ? draft.text : draft.backup,
      remote: undefined,
      error: undefined,
      status: choice === 'server' ? 'saved' : 'dirty',
    });
    if (choice === 'mine') void this.save(key);
  }
  restore(project: string, path: string) {
    const draft = this.get(project, path);
    if (draft?.backup === undefined) return;
    this.edit(project, path, draft.backup);
  }
  assertCanChange(project: string, path: string) {
    if (
      this.all().some(
        (draft) => draft.project === project && inside(draft.path, path) && hasDraftChanges(draft),
      )
    )
      throw new ApiError(
        0,
        'unsaved_changes',
        'Сначала сохраните изменения в открытых файлах или разрешите конфликт.',
      );
  }
  changed(project: string, change: { kind: string; path?: string; from?: string; to?: string }) {
    for (const [key, draft] of this.entries) {
      if (draft.project !== project || hasDraftChanges(draft)) continue;
      if (change.kind === 'delete' && change.path && inside(draft.path, change.path))
        this.entries.delete(key);
      if (change.kind === 'move' && change.from && change.to && inside(draft.path, change.from)) {
        const path = change.to + draft.path.slice(change.from.length);
        this.entries.delete(key);
        this.entries.set(keyOf(project, path), { ...draft, path });
      }
    }
    this.revision++;
    for (const listener of this.listeners) listener();
  }
  pause() {
    this.active = false;
    for (const key of this.timers.keys()) this.cancelTimer(key);
    for (const controller of this.saves.values()) controller.abort();
    for (const controller of this.loads.values()) controller.abort();
    this.loads.clear();
    this.saves.clear();
    for (const [key, draft] of this.entries)
      if (draft.status === 'saving') this.patch(key, { status: 'dirty' });
  }
  resume() {
    this.active = true;
    for (const [key, draft] of this.entries) {
      if (!draft.etag) void this.load(key);
      else this.schedule(key);
    }
  }
}
