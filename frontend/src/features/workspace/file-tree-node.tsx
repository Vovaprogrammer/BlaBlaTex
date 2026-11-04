import {
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  LockKeyhole,
  MoreHorizontal,
} from 'lucide-react';
import { ContextMenu, DropdownMenu } from 'radix-ui';
import type { NodeRendererProps } from 'react-arborist';
import { cn } from '@/lib/utils';
import { parentPath, withinPath, type FileNode } from './file-tree-data';
import { useFileTree } from './file-tree-context';

const menuClass = 'z-40 min-w-48 rounded-xl border bg-card p-1 shadow-xl';
function ActionItems({ data, context = false }: { data: FileNode; context?: boolean }) {
  const { act, busy } = useFileTree();
  const Item = context ? ContextMenu.Item : DropdownMenu.Item;
  const base = data.children ? data.id : parentPath(data.id);
  const actions = [
    ['create-file', 'Создать файл', false, base],
    ['create-folder', 'Создать папку', false, base],
    ['rename', 'Переименовать', data.protected || data.section, data.id],
    ['move', 'Переместить', data.protected || data.section, data.id],
    ['delete', 'Удалить', data.protected || data.section, data.id],
  ] as const;
  return (
    <>
      {actions.map(([kind, label, disabled, path]) => (
        <Item
          key={kind}
          disabled={busy || disabled}
          onSelect={() => act({ kind, path, folder: Boolean(data.children) })}
          className="cursor-pointer rounded-lg px-3 py-2 text-sm outline-none data-[disabled]:pointer-events-none data-[disabled]:opacity-40 data-[highlighted]:bg-accent"
        >
          {label}
        </Item>
      ))}
    </>
  );
}

export function FileTreeNode({ node, style, dragHandle }: NodeRendererProps<FileNode>) {
  const { data } = node;
  const { open, upload } = useFileTree();
  const dir = node.isInternal ? data.id : parentPath(data.id);
  const Icon = node.isInternal ? (node.isOpen ? FolderOpen : Folder) : FileText;
  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger asChild>
        <div
          ref={dragHandle}
          onDragOverCapture={(event) => {
            if (withinPath(dir, 'materials') && event.dataTransfer.types.includes('Files')) {
              event.preventDefault();
              event.stopPropagation();
            }
          }}
          onDropCapture={(event) => {
            if (withinPath(dir, 'materials') && event.dataTransfer.types.includes('Files')) {
              event.preventDefault();
              event.stopPropagation();
              if (node.isInternal) node.open();
              else node.parent?.open();
              upload?.(Array.from(event.dataTransfer.files), dir);
            }
          }}
          onContextMenu={() => node.select()}
          style={style}
          className={cn(
            'flex h-full min-w-0 items-center gap-1 rounded-lg pr-1',
            node.isSelected && 'bg-accent',
            data.section && 'border-t',
          )}
        >
          <button
            type="button"
            aria-label={`${node.isInternal ? 'Папка' : 'Открыть'} ${data.name}`}
            onClick={(event) => {
              event.stopPropagation();
              node.select();
              if (node.isInternal) node.toggle();
              else if (data.file) open(data.file);
            }}
            className="flex h-full min-w-0 flex-1 items-center gap-2 rounded-lg px-1 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            title={
              data.file?.role === 'generated'
                ? `${data.id} — создаётся автоматически, только чтение`
                : data.id
            }
          >
            {node.isInternal ? (
              node.isOpen ? (
                <ChevronDown className="size-3 shrink-0" aria-hidden="true" />
              ) : (
                <ChevronRight className="size-3 shrink-0" aria-hidden="true" />
              )
            ) : (
              <span className="w-3 shrink-0" />
            )}
            <Icon className="size-5 shrink-0 text-ring" aria-hidden="true" />
            <span className="truncate">{data.name}</span>
            {data.file?.role === 'generated' && (
              <>
                <LockKeyhole className="size-3 shrink-0 text-muted-foreground" aria-hidden="true" />
                <span className="sr-only">Создаётся автоматически, только чтение</span>
              </>
            )}
          </button>
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button
                type="button"
                aria-label={`Действия для ${data.id}`}
                className="flex size-8 shrink-0 items-center justify-center rounded-lg outline-none hover:bg-secondary focus-visible:ring-2 focus-visible:ring-ring"
                onClick={(event) => event.stopPropagation()}
              >
                <MoreHorizontal className="size-4" aria-hidden="true" />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content align="end" className={menuClass}>
                <ActionItems data={data} />
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        </div>
      </ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content className={menuClass}>
          <ActionItems data={data} context />
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  );
}
