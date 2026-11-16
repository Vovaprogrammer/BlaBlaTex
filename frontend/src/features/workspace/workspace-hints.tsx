import { useState } from 'react';
import { Link } from 'react-router';
import { Button } from '@/components/ui/button';

const storageKey = 'bbt-workspace-hints-hidden';

function readHidden() {
  try {
    return localStorage.getItem(storageKey) === '1';
  } catch {
    return false;
  }
}

export function WorkspaceHints() {
  const [hidden, setHidden] = useState(readHidden);
  if (hidden) return null;

  function dismiss() {
    setHidden(true);
    try {
      localStorage.setItem(storageKey, '1');
    } catch {
      // Закрытие работает и без доступа к хранилищу.
    }
  }

  return (
    <section
      aria-label="Подсказки для первого проекта"
      className="mx-3 mt-3 flex max-h-[35svh] shrink-0 flex-wrap items-start gap-x-4 gap-y-2 overflow-y-auto rounded-xl border bg-card px-3 py-2 sm:mx-6"
    >
      <details className="min-w-0 basis-full sm:basis-0 sm:grow">
        <summary className="w-fit cursor-pointer rounded-md py-1 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-ring">
          С чего начать
        </summary>
        <ul className="mt-2 grid gap-2 text-sm text-muted-foreground lg:grid-cols-3">
          <li>В разделе «Файлы» добавьте методичку, код и скриншоты в «Материалы».</li>
          <li>В чате напишите помощнику, какой отчёт нужно подготовить.</li>
          <li>В разделе PDF нажмите «Собрать PDF», чтобы проверить готовый документ.</li>
        </ul>
        <Link
          to="/help"
          target="_blank"
          className="mt-2 inline-block rounded text-sm text-ring underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-ring"
        >
          Подробнее — в помощи
          <span className="sr-only"> (в новой вкладке)</span>
        </Link>
      </details>
      <Button variant="ghost" size="sm" onClick={dismiss}>
        Больше не показывать
      </Button>
    </section>
  );
}
