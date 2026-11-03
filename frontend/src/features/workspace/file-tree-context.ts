import { createContext, useContext } from 'react';
import type { FileAction } from './file-actions';
import type { ProjectFile } from './file-tree-data';

export const FileTreeContext = createContext<{
  busy: boolean;
  act: (action: FileAction) => void;
  open: (file: ProjectFile) => void;
}>({ busy: false, act: () => {}, open: () => {} });
export const useFileTree = () => useContext(FileTreeContext);
