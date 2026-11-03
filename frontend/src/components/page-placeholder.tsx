export function PagePlaceholder({ title, description }: { title: string; description: string }) {
  return (
    <section>
      <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-3 max-w-xl leading-relaxed text-muted-foreground">{description}</p>
    </section>
  );
}
