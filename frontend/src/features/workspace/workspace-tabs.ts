import { withinPath } from './file-tree-data';
import type { FileChange } from './file-actions';

export type WorkspaceTabs = { paths: string[]; active: string | null };
export const initialTabs: WorkspaceTabs = { paths: [], active: null };
export type TabAction =
  | { kind: 'open'; path: string }
  | { kind: 'select'; path: string | null }
  | { kind: 'close'; path: string }
  | { kind: 'change'; change: FileChange }
  | { kind: 'prune'; paths: string[] };
export function tabsReducer(state: WorkspaceTabs, action: TabAction): WorkspaceTabs {
  switch (action.kind) {
    case 'open':
      return {
        paths: state.paths.includes(action.path) ? state.paths : [...state.paths, action.path],
        active: action.path,
      };
    case 'select':
      return {
        ...state,
        active:
          action.path === null || state.paths.includes(action.path) ? action.path : state.active,
      };
    case 'close': {
      const index = state.paths.indexOf(action.path);
      const paths = state.paths.filter((path) => path !== action.path);
      return {
        paths,
        active:
          state.active !== action.path ? state.active : (paths[index] ?? paths.at(-1) ?? null),
      };
    }
    case 'change': {
      const change = action.change;
      if (change.kind === 'create')
        return change.folder ? state : tabsReducer(state, { kind: 'open', path: change.path });
      if (change.kind === 'move') {
        const move = (path: string) =>
          withinPath(path, change.from) ? change.to + path.slice(change.from.length) : path;
        return {
          paths: state.paths.map(move),
          active: state.active === null ? null : move(state.active),
        };
      }
      const paths = state.paths.filter((path) => !withinPath(path, change.path));
      return {
        paths,
        active: state.active !== null && paths.includes(state.active) ? state.active : null,
      };
    }
    case 'prune': {
      const paths = state.paths.filter((path) => action.paths.includes(path));
      if (paths.length === state.paths.length) return state;
      return {
        paths,
        active: state.active !== null && paths.includes(state.active) ? state.active : null,
      };
    }
  }
}
