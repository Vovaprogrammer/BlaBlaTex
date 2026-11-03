import { Component, type ReactNode } from 'react';
import { Button } from '@/components/ui/button';

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <main role="alert" className="mx-auto max-w-xl space-y-4 px-6 py-20">
        <h1 className="text-2xl font-semibold">Не удалось открыть страницу</h1>
        <p className="text-muted-foreground">Попробуйте перезагрузить страницу.</p>
        <Button onClick={() => window.location.reload()}>Перезагрузить</Button>
      </main>
    );
  }
}
