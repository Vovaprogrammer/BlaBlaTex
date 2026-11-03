import { createContext, useContext, useSyncExternalStore } from 'react';
import type { DraftStore } from './draft-store';

export const DraftContext = createContext<DraftStore | null>(null);
export function useDraftStore() {
  const store = useContext(DraftContext);
  if (!store) throw new Error('Редактор должен находиться внутри провайдера черновиков');
  return store;
}
export function useDraftRevision() {
  const store = useDraftStore();
  return useSyncExternalStore(store.subscribe, store.snapshot, store.snapshot);
}
