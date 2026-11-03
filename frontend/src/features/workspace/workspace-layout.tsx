import { useState, useSyncExternalStore, type ReactNode } from 'react';
import { Group, Panel, Separator } from 'react-resizable-panels';
import { readPanelLayout, savePanelLayout } from './workspace-preferences';

function subscribe(listener: () => void) {
  const media = window.matchMedia?.('(max-width: 767px)');
  media?.addEventListener('change', listener);
  return () => media?.removeEventListener('change', listener);
}
function isMobile() {
  return window.matchMedia?.('(max-width: 767px)').matches ?? false;
}

export type MobileSection = 'files' | 'chat' | 'document';
const sections = [
  ['files', 'Файлы'],
  ['chat', 'Чат'],
  ['document', 'PDF'],
] as const;

export function WorkspaceLayout({
  files,
  chat,
  document,
  section,
  onSectionChange,
}: {
  files: ReactNode;
  chat: ReactNode;
  document: ReactNode;
  section: MobileSection;
  onSectionChange: (section: MobileSection) => void;
}) {
  const mobile = useSyncExternalStore(subscribe, isMobile, () => false);
  const [layout] = useState(readPanelLayout);
  if (mobile)
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-3 p-3">
        <div
          role="tablist"
          aria-label="Панели рабочего окна"
          className="grid grid-cols-3 gap-2"
          onKeyDown={(event) => {
            const index = sections.findIndex(([value]) => value === section);
            const next =
              event.key === 'ArrowRight'
                ? (index + 1) % sections.length
                : event.key === 'ArrowLeft'
                  ? (index + sections.length - 1) % sections.length
                  : event.key === 'Home'
                    ? 0
                    : event.key === 'End'
                      ? sections.length - 1
                      : null;
            if (next === null) return;
            event.preventDefault();
            const value = sections[next]?.[0] ?? 'chat';
            onSectionChange(value);
            event.currentTarget.querySelector<HTMLButtonElement>(`#mobile-${value}`)?.focus();
          }}
        >
          {sections.map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="tab"
              id={`mobile-${value}`}
              aria-selected={section === value}
              aria-controls="mobile-panel"
              tabIndex={section === value ? 0 : -1}
              onClick={() => onSectionChange(value)}
              className={`min-h-11 rounded-xl border px-3 focus-visible:outline-2 focus-visible:outline-ring ${section === value ? 'border-ring bg-primary text-primary-foreground' : 'bg-card'}`}
            >
              {label}
            </button>
          ))}
        </div>
        <div
          role="tabpanel"
          id="mobile-panel"
          aria-labelledby={`mobile-${section}`}
          className="min-h-0 flex-1 overflow-hidden rounded-2xl border bg-card"
        >
          {{ files, chat, document }[section]}
        </div>
      </div>
    );
  return (
    <div className="min-h-0 flex-1 p-4 lg:p-6">
      <Group
        id="workspace-panels"
        orientation="horizontal"
        defaultLayout={layout}
        onLayoutChanged={(value, meta) => {
          if (meta.isUserInteraction) savePanelLayout(meta.requestedLayout ?? value);
        }}
        className="h-full min-h-0"
      >
        <Panel
          id="files"
          defaultSize="20%"
          minSize="145px"
          className="h-full min-w-0 overflow-hidden rounded-2xl border bg-card"
        >
          {files}
        </Panel>
        <Separator
          aria-label="Изменить ширину файлов и чата"
          className="mx-1 w-2 rounded-md outline-none focus-visible:bg-ring hover:bg-ring/30"
        />
        <Panel
          id="chat"
          defaultSize="44%"
          minSize="200px"
          className="h-full min-w-0 overflow-hidden rounded-2xl border bg-card"
        >
          {chat}
        </Panel>
        <Separator
          aria-label="Изменить ширину чата и документа"
          className="mx-1 w-2 rounded-md outline-none focus-visible:bg-ring hover:bg-ring/30"
        />
        <Panel
          id="document"
          defaultSize="36%"
          minSize="235px"
          className="h-full min-w-0 overflow-hidden rounded-2xl border bg-card"
        >
          {document}
        </Panel>
      </Group>
    </div>
  );
}
