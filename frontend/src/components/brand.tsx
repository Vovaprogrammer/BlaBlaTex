export function Brand({ large = false }: { large?: boolean }) {
  return (
    <span
      className={
        large
          ? 'inline-flex items-center gap-4 text-3xl font-bold tracking-tight sm:gap-5 sm:text-4xl'
          : 'inline-flex items-center gap-3 text-xl font-bold tracking-tight sm:text-2xl'
      }
    >
      <svg
        className={
          large ? 'h-20 w-16 shrink-0 text-ring sm:h-24 sm:w-20' : 'h-12 w-9 shrink-0 text-ring'
        }
        viewBox="0 0 64 86"
        fill="none"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M32 3v35 M23 13h18 M23 23h18 M32 38L5 80h54z M23 65h18" />
      </svg>
      BlaBlaTex
    </span>
  );
}
