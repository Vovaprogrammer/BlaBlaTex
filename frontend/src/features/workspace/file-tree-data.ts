import type { components } from '@/api/schema';

export type ProjectFile = components['schemas']['FileInfo'];
export type FileNode = {
  id: string;
  name: string;
  file?: ProjectFile;
  children?: FileNode[];
  protected: boolean;
  section: boolean;
};
export const fileName = (path: string) => path.split('/').at(-1) ?? path;
export const parentPath = (path: string) => path.split('/').slice(0, -1).join('/');
export const joinPath = (parent: string, name: string) => (parent ? `${parent}/${name}` : name);
export const withinPath = (path: string, parent: string) =>
  path === parent || path.startsWith(parent + '/');

export function buildFileTree(items: ProjectFile[]): FileNode[] {
  const nodes = new Map<string, FileNode>();
  function folder(path: string): FileNode {
    const existing = nodes.get(path);
    if (existing) return existing;
    const node: FileNode = {
      id: path,
      name: path === 'materials' ? 'Материалы' : fileName(path),
      children: [],
      protected: false,
      section: path === 'materials',
    };
    nodes.set(path, node);
    return node;
  }
  folder('materials');
  for (const item of items) {
    const parts = item.path.split('/');
    for (let i = 1; i < parts.length; i++) folder(parts.slice(0, i).join('/'));
    const node =
      item.kind === 'folder'
        ? folder(item.path)
        : {
            id: item.path,
            name: fileName(item.path),
            protected: item.role === 'generated',
            section: false,
          };
    node.file = item;
    nodes.set(item.path, node);
  }
  const roots: FileNode[] = [];
  for (const node of nodes.values()) {
    const parent = nodes.get(parentPath(node.id));
    if (parent?.children) parent.children.push(node);
    else roots.push(node);
  }
  function sort(nodes: FileNode[]) {
    nodes.sort(
      (a, b) =>
        Number(a.section) - Number(b.section) ||
        Number(!a.children) - Number(!b.children) ||
        a.name.localeCompare(b.name, 'ru', { numeric: true }),
    );
    for (const node of nodes) {
      if (node.children) {
        sort(node.children);
        node.protected ||= node.children.some((child) => child.protected);
      }
    }
  }
  sort(roots);
  return roots;
}
