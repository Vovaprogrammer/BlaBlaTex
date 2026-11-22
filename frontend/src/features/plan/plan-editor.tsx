import { useState } from 'react';
import { ArrowDown, ArrowUp, X } from 'lucide-react';
import { ApiError, isRecord } from '@/api/api-error';
import { errorMessage } from '@/app/query-client';
import { Button } from '@/components/ui/button';
import { useSaveReportPlan, type Plan } from './plan-data';

type Section = Plan['plan']['sections'][number];
const maxNoteLength = 2000;
const shortPath = (path: string) => path.replace(/^materials\//, '');

function moveMaterial(materials: string[], position: number, offset: number) {
  const changed = [...materials];
  const [path] = changed.splice(position, 1);
  if (path !== undefined) changed.splice(position + offset, 0, path);
  return changed;
}

function validationMessages(error: unknown) {
  const details = error instanceof ApiError ? error.details.errors : undefined;
  return Array.isArray(details)
    ? details.flatMap((item: unknown) =>
        isRecord(item) && typeof item.message === 'string' ? [item.message] : [],
      )
    : [];
}

export function PlanEditor({
  id,
  plan,
  locked,
  onClose,
}: {
  id: string;
  plan: Plan;
  locked: boolean;
  onClose: () => void;
}) {
  const [sections, setSections] = useState(plan.plan.sections);
  const [baseVersion] = useState(plan.updated_at);
  const save = useSaveReportPlan(id);
  const stale = baseVersion !== plan.updated_at;
  const tooLong = sections.some((section) => Array.from(section.note).length > maxNoteLength);
  const available = [
    ...new Set([
      ...plan.plan.sections.flatMap((section) => section.materials),
      ...plan.plan.unassigned,
    ]),
  ].sort();
  const inputClass =
    'w-full rounded-md border bg-background px-2 py-1.5 text-sm focus-visible:outline-2 focus-visible:outline-ring';

  function update(sectionId: string, changes: Partial<Pick<Section, 'note' | 'materials'>>) {
    setSections((items) =>
      items.map((item) => (item.section_id === sectionId ? { ...item, ...changes } : item)),
    );
  }

  return (
    <form
      aria-label="Правка плана"
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (locked || stale || tooLong || save.isPending) return;
        save.mutate(
          {
            sections: sections.map(({ section_id, note, materials }) => ({
              section_id,
              note,
              materials,
            })),
          },
          { onSuccess: onClose },
        );
      }}
    >
      {stale && (
        <p role="alert" className="text-sm text-destructive">
          План обновился. Отмените правки и откройте новую версию плана.
        </p>
      )}
      {save.error && (
        <div role="alert" className="space-y-1 text-sm text-destructive">
          <p>{errorMessage(save.error)}</p>
          {validationMessages(save.error).map((message, index) => (
            <p key={index}>{message}</p>
          ))}
        </div>
      )}
      <fieldset disabled={locked || save.isPending} className="min-w-0 space-y-3">
        {sections.map(({ section_id, title, note, materials }) => (
          <section key={section_id} className="space-y-2 rounded-xl border bg-card p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-semibold">{title}</h3>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                aria-label={`Очистить раздел «${title}»`}
                disabled={!note && materials.length === 0}
                onClick={() => update(section_id, { note: '', materials: [] })}
              >
                Очистить
              </Button>
            </div>
            <label className="block space-y-1 text-sm">
              <span>Заметка</span>
              <textarea
                rows={3}
                className={inputClass}
                aria-label={`Заметка — ${title}`}
                aria-invalid={Array.from(note).length > maxNoteLength || undefined}
                value={note}
                onChange={(event) => update(section_id, { note: event.currentTarget.value })}
              />
            </label>
            {Array.from(note).length > maxNoteLength && (
              <p className="text-sm text-destructive">Сократите заметку до 2000 символов.</p>
            )}
            <ul aria-label={`Материалы — ${title}`} className="space-y-1 text-sm">
              {materials.map((path, index) => (
                <li key={path} className="flex flex-wrap items-center justify-between gap-1">
                  <span className="min-w-0 [overflow-wrap:anywhere]" title={path}>
                    {shortPath(path)}
                  </span>
                  <div className="flex shrink-0 gap-1">
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      aria-label={`Выше: ${shortPath(path)}`}
                      disabled={index === 0}
                      onClick={() =>
                        update(section_id, { materials: moveMaterial(materials, index, -1) })
                      }
                    >
                      <ArrowUp aria-hidden="true" />
                    </Button>
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      aria-label={`Ниже: ${shortPath(path)}`}
                      disabled={index === materials.length - 1}
                      onClick={() =>
                        update(section_id, { materials: moveMaterial(materials, index, 1) })
                      }
                    >
                      <ArrowDown aria-hidden="true" />
                    </Button>
                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      aria-label={`Убрать: ${shortPath(path)}`}
                      onClick={() =>
                        update(section_id, { materials: materials.filter((item) => item !== path) })
                      }
                    >
                      <X aria-hidden="true" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
            <select
              value=""
              className={inputClass}
              aria-label={`Добавить материал — ${title}`}
              disabled={
                materials.length >= 500 || available.every((path) => materials.includes(path))
              }
              onChange={(event) =>
                update(section_id, { materials: [...materials, event.currentTarget.value] })
              }
            >
              <option value="" disabled>
                Добавить материал
              </option>
              {available
                .filter((path) => !materials.includes(path))
                .map((path) => (
                  <option key={path} value={path}>
                    {shortPath(path)}
                  </option>
                ))}
            </select>
          </section>
        ))}
      </fieldset>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" disabled={locked || stale || tooLong || save.isPending}>
          {save.isPending ? 'Сохраняем…' : 'Сохранить план'}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={save.isPending}
          onClick={onClose}
        >
          Отменить правки
        </Button>
      </div>
    </form>
  );
}
