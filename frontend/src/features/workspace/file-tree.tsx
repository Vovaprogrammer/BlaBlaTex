import { useEffect, useMemo, useRef, useState } from 'react';
import { FilePlus2, FolderPlus, RefreshCw } from 'lucide-react';
import { Tree, type TreeApi } from 'react-arborist';
import { Button } from '@/components/ui/button';
import { errorMessage } from '@/app/query-client';
import { useProjectTree } from './workspace-queries';
import {
  buildFileTree,
  joinPath,
  parentPath,
  withinPath,
  type FileNode,
  type ProjectFile,
} from './file-tree-data';
import { FileTreeNode } from './file-tree-node';
import { FileTreeContext } from './file-tree-context';
import { fileErrorMessage, useFileAction, type FileAction, type FileChange } from './file-actions';
import { FileActionDialog } from './file-action-dialog';

export function FileTree({
  id,
  onOpen,
  onChange,
}: {
  id: string;
  onOpen: (file: ProjectFile) => void;
  onChange: (change: FileChange) => void;
}) {
  const files = useProjectTree(id);
  const data = useMemo(() => buildFileTree(files.data?.items ?? []), [files.data]);
  const [action, setAction] = useState<FileAction | null>(null);
  const [selectedFolder, setSelectedFolder] = useState('');
  const operation = useFileAction(id, onChange);
  const container = useRef<HTMLDivElement>(null);
  const tree = useRef<TreeApi<FileNode>>(null);
  const [height, setHeight] = useState(300);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => {
      if (entry && entry.contentRect.height > 0) setHeight(entry.contentRect.height);
    });
    if (container.current) observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  function act(next: FileAction) {
    if (next.kind === 'create-file' || next.kind === 'create-folder') {
      const folder = tree.current?.get(next.path);
      next = { ...next, path: folder?.isInternal ? next.path : '' };
      folder?.open();
    }
    operation.reset();
    setAction(next);
  }
  return (
    <FileTreeContext.Provider value={{ busy: operation.isPending, act, open: onOpen }}>
      <div className="flex min-h-0 flex-1 flex-col gap-2 p-2">
        <div className="flex items-center gap-1 px-1">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Создать файл"
            disabled={operation.isPending}
            onClick={() => act({ kind: 'create-file', path: selectedFolder })}
          >
            <FilePlus2 aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Создать папку"
            disabled={operation.isPending}
            onClick={() => act({ kind: 'create-folder', path: selectedFolder })}
          >
            <FolderPlus aria-hidden="true" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Обновить файлы"
            disabled={files.isFetching}
            onClick={() => void files.refetch()}
            className="ml-auto"
          >
            <RefreshCw aria-hidden="true" />
          </Button>
        </div>
        {files.isPending && (
          <p role="status" className="p-2 text-sm">
            Загружаем файлы…
          </p>
        )}
        {files.isError && (
          <div role="alert" className="space-y-2 p-2 text-sm">
            <p>{errorMessage(files.error)}</p>
            <Button variant="outline" onClick={() => void files.refetch()}>
              Повторить
            </Button>
          </div>
        )}
        {operation.isError && !action && (
          <p role="alert" className="break-words p-2 text-sm text-destructive">
            {fileErrorMessage(operation.error)}
          </p>
        )}
        <div
          ref={container}
          className="min-h-0 flex-1"
          onKeyDown={(event) => {
            if (
              event.key === 'Enter' &&
              event.target === event.currentTarget.querySelector('[role=tree]')
            ) {
              event.preventDefault();
              const node = tree.current?.focusedNode;
              if (node?.isInternal) node.toggle();
              else if (node?.data.file) onOpen(node.data.file);
            }
          }}
        >
          {files.data && (
            <Tree<FileNode>
              ref={tree}
              data={data}
              width="100%"
              height={height}
              rowHeight={40}
              indent={16}
              padding={4}
              openByDefault
              disableMultiSelection
              disableEdit
              onSelect={(nodes) => {
                const node = nodes[0];
                setSelectedFolder(node ? (node.data.children ? node.id : parentPath(node.id)) : '');
              }}
              disableDrag={(node) => operation.isPending || node.protected || node.section}
              disableDrop={({ parentNode, dragNodes }) =>
                operation.isPending ||
                dragNodes.some(
                  (node) =>
                    node.data.protected ||
                    node.data.section ||
                    (parentNode && withinPath(parentNode.id, node.id)),
                )
              }
              onMove={({ dragNodes, parentNode }) => {
                const node = dragNodes[0];
                if (!node) return;
                const to = joinPath(parentNode?.id ?? '', node.data.name);
                if (to !== node.id)
                  operation.mutate({ action: { kind: 'move', path: node.id }, value: to });
              }}
              onActivate={(node) => {
                if (node.isInternal) node.toggle();
                else if (node.data.file) onOpen(node.data.file);
              }}
              aria-label="Дерево файлов проекта"
            >
              {FileTreeNode}
            </Tree>
          )}
        </div>
        {files.data && files.data.items.every((item) => !withinPath(item.path, 'materials')) && (
          <p className="px-2 text-xs text-muted-foreground">Материалов пока нет</p>
        )}
      </div>
      {action && (
        <FileActionDialog
          key={`${action.kind}:${action.path}`}
          action={action}
          pending={operation.isPending}
          error={operation.isError ? fileErrorMessage(operation.error) : undefined}
          onClose={() => setAction(null)}
          onSubmit={(value) =>
            operation.mutate({ action, value }, { onSuccess: () => setAction(null) })
          }
        />
      )}
    </FileTreeContext.Provider>
  );
}
