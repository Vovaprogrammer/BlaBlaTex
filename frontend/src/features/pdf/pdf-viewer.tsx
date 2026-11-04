import { useEffect, useRef, useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from 'lucide-react';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import { Button } from '@/components/ui/button';
import { clampPage, type PdfPosition } from './pdf-position';
import 'react-pdf/dist/Page/TextLayer.css';
import 'react-pdf/dist/Page/AnnotationLayer.css';

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();
const options = {
  cMapUrl: `${import.meta.env.BASE_URL}cmaps/`,
  standardFontDataUrl: `${import.meta.env.BASE_URL}standard_fonts/`,
  wasmUrl: `${import.meta.env.BASE_URL}wasm/`,
};

export function PdfViewer({ blob, position }: { blob: Blob; position: PdfPosition }) {
  const container = useRef<HTMLDivElement>(null);
  const restoring = useRef(true);
  const [count, setCount] = useState(0);
  const [page, setPage] = useState(() => position.get().page);
  const [zoom, setZoom] = useState(() => position.get().zoom);
  const [width, setWidth] = useState(400);
  const [ready, setReady] = useState<Blob | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const pageWidth = zoom === 'fit' ? Math.max(100, width - 32) : 595 * zoom;
  useEffect(() => {
    const node = container.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (ready !== blob || !container.current) return;
    restoring.current = true;
    const frame = requestAnimationFrame(() => {
      const node = container.current;
      const target = node?.querySelector<HTMLElement>(
        `[data-pdf-page="${clampPage(position.get().page, count)}"]`,
      );
      if (node && target)
        node.scrollTop = target.offsetTop + position.get().offset * target.offsetHeight;
      restoring.current = false;
    });
    return () => cancelAnimationFrame(frame);
  }, [ready, blob, count, width, zoom, position]);
  function jump(value: number) {
    const next = clampPage(value, count);
    const node = container.current;
    const target = node?.querySelector<HTMLElement>(`[data-pdf-page="${next}"]`);
    if (node && target) node.scrollTop = target.offsetTop;
    position.set({ page: next, offset: 0 });
    setPage(next);
  }
  function scale(value: 'fit' | number) {
    position.set({ zoom: value });
    setZoom(value);
  }
  function loaded(document: PDFDocumentProxy) {
    setCount(document.numPages);
    position.set({ page: clampPage(position.get().page, document.numPages) });
    setPage(position.get().page);
    setReady(blob);
    setError(false);
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        aria-label="Управление PDF"
        className="flex shrink-0 flex-wrap items-center gap-1 border-b p-2"
      >
        <Button
          variant="ghost"
          size="icon"
          aria-label="Предыдущая страница"
          disabled={page <= 1 || !count}
          onClick={() => jump(page - 1)}
        >
          <ChevronLeft />
        </Button>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            jump(Number(data.get('page')));
          }}
        >
          <input
            key={page}
            name="page"
            aria-label="Номер страницы PDF"
            type="number"
            min={1}
            max={count || 1}
            defaultValue={page}
            disabled={!count}
            className="h-9 w-14 rounded-lg border bg-secondary px-2 text-center text-sm"
          />
        </form>
        <span className="text-sm text-muted-foreground">/ {count || '—'}</span>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Следующая страница"
          disabled={page >= count || !count}
          onClick={() => jump(page + 1)}
        >
          <ChevronRight />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Уменьшить PDF"
          onClick={() => scale(Math.max(0.5, (zoom === 'fit' ? pageWidth / 595 : zoom) - 0.25))}
        >
          <ZoomOut />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Увеличить PDF"
          onClick={() => scale(Math.min(2, (zoom === 'fit' ? pageWidth / 595 : zoom) + 0.25))}
        >
          <ZoomIn />
        </Button>
        <select
          aria-label="Масштаб PDF"
          value={zoom}
          onChange={(event) =>
            scale(event.target.value === 'fit' ? 'fit' : Number(event.target.value))
          }
          className="h-9 max-w-full rounded-lg border bg-secondary px-2 text-sm"
        >
          <option value="fit">По ширине</option>
          {[0.5, 0.75, 1, 1.25, 1.5, 2, ...(typeof zoom === 'number' ? [zoom] : [])]
            .filter((value, index, values) => values.indexOf(value) === index)
            .sort((a, b) => a - b)
            .map((value) => (
              <option key={value} value={value}>
                {Math.round(value * 100)}%
              </option>
            ))}
        </select>
      </div>
      <div
        ref={container}
        aria-label="Страницы PDF"
        className="relative min-h-0 flex-1 overflow-auto bg-background p-4"
        onScroll={() => {
          const node = container.current;
          if (!node || restoring.current || ready !== blob) return;
          const pages = [...node.querySelectorAll<HTMLElement>('[data-pdf-page]')];
          const current =
            pages.reverse().find((entry) => entry.offsetTop <= node.scrollTop + 20) ?? pages.at(-1);
          if (current) {
            position.set({
              page: Number(current.dataset.pdfPage),
              offset: Math.max(0, (node.scrollTop - current.offsetTop) / current.offsetHeight),
            });
            setPage(position.get().page);
          }
        }}
      >
        <Document
          key={attempt}
          file={blob}
          options={options}
          suspense={false}
          onLoadSuccess={loaded}
          onLoadError={() => setError(true)}
          loading={<p role="status">Открываем PDF…</p>}
          error={
            <p role="alert">
              Не удалось открыть PDF. Попробуйте скачать файл или повторить загрузку.
            </p>
          }
        >
          {Array.from({ length: count }, (_, index) => (
            <LazyPage key={index} number={index + 1} width={pageWidth} root={container} />
          ))}
        </Document>
        {error && (
          <Button
            variant="outline"
            onClick={() => {
              setError(false);
              setReady(null);
              setCount(0);
              setAttempt((value) => value + 1);
            }}
          >
            Повторить открытие PDF
          </Button>
        )}
      </div>
    </div>
  );
}

function LazyPage({
  number,
  width,
  root,
}: {
  number: number;
  width: number;
  root: React.RefObject<HTMLDivElement | null>;
}) {
  const node = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(number === 1);
  const [ratio, setRatio] = useState(842 / 595);
  useEffect(() => {
    if (!node.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => setVisible(Boolean(entry?.isIntersecting)),
      { root: root.current, rootMargin: '600px' },
    );
    observer.observe(node.current);
    return () => observer.disconnect();
  }, [root]);
  return (
    <div
      ref={node}
      data-pdf-page={number}
      aria-label={`Страница ${number}`}
      className="mx-auto mb-4 overflow-hidden bg-white shadow"
      style={{ width, height: width * ratio }}
    >
      {visible && (
        <Page
          pageNumber={number}
          width={width}
          suspense={false}
          onLoadSuccess={(page) => setRatio(page.originalHeight / page.originalWidth)}
          loading={<p className="p-4 text-black">Страница {number}…</p>}
          error={
            <p role="alert" className="p-4 text-black">
              Не удалось открыть страницу {number}
            </p>
          }
        />
      )}
    </div>
  );
}
