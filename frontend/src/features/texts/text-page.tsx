import { useEffect } from 'react';
import Markdown, { type Components } from 'react-markdown';
import { Link } from 'react-router';
import { Brand } from '@/components/brand';
import { ThemeToggle } from '@/components/theme-toggle';
import consent from './consent.md?raw';
import help from './help.md?raw';
import privacy from './privacy.md?raw';

const linkClass =
  'rounded text-ring underline underline-offset-4 focus-visible:outline-2 focus-visible:outline-ring';

// Тексты пишет команда, но HTML в них всё равно не исполняется: react-markdown его экранирует.
const components: Components = {
  h1: ({ children }) => <h1 className="text-3xl font-bold sm:text-4xl">{children}</h1>,
  h2: ({ children }) => <h2 className="mt-10 text-xl font-semibold sm:text-2xl">{children}</h2>,
  p: ({ children }) => <p className="mt-4 leading-relaxed">{children}</p>,
  ul: ({ children }) => <ul className="mt-4 list-disc space-y-2 pl-6">{children}</ul>,
  ol: ({ children }) => <ol className="mt-4 list-decimal space-y-2 pl-6">{children}</ol>,
  li: ({ children }) => <li className="pl-1 leading-relaxed">{children}</li>,
  code: ({ children }) => (
    <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]">{children}</code>
  ),
  img: ({ alt }) => <span>{alt}</span>,
  a: ({ href = '', children }) =>
    href.startsWith('/') ? (
      <Link to={href} className={linkClass}>
        {children}
      </Link>
    ) : (
      <a href={href} target="_blank" rel="noreferrer" className={linkClass}>
        {children}
        <span className="sr-only"> (в новой вкладке)</span>
      </a>
    ),
};

function TextPage({ text }: { text: string }) {
  // Ссылка из конца согласия на политику открывает политику с начала, а не с той же высоты.
  useEffect(() => {
    if (document.scrollingElement) document.scrollingElement.scrollTop = 0;
  }, [text]);
  return (
    <div className="min-h-svh">
      <header className="mx-auto flex max-w-3xl items-center justify-between gap-4 px-4 pt-6 sm:px-6">
        <Link
          to="/"
          aria-label="BlaBlaTex — на главную"
          className="rounded-md focus-visible:outline-2 focus-visible:outline-ring"
        >
          <Brand />
        </Link>
        <ThemeToggle />
      </header>
      <main className="mx-auto max-w-3xl break-words px-4 pb-16 pt-10 sm:px-6">
        <article>
          <Markdown components={components}>{text}</Markdown>
        </article>
        <nav
          aria-label="Другие страницы"
          className="mt-12 flex flex-wrap gap-x-6 gap-y-2 border-t pt-6 text-sm"
        >
          <Link to="/" className={linkClass}>
            На главную
          </Link>
          <Link to="/help" className={linkClass}>
            Помощь
          </Link>
          <Link to="/privacy" className={linkClass}>
            Политика конфиденциальности
          </Link>
          <Link to="/consent" className={linkClass}>
            Согласие на обработку данных
          </Link>
        </nav>
      </main>
    </div>
  );
}

export function ConsentPage() {
  return <TextPage text={consent} />;
}

export function PrivacyPage() {
  return <TextPage text={privacy} />;
}

export function HelpPage() {
  return <TextPage text={help} />;
}
