export async function startMocks() {
  if (import.meta.env.DEV && import.meta.env.VITE_USE_MOCKS === '1') {
    const { worker } = await import('@/mocks/browser');
    await worker.start({ quiet: true, onUnhandledFrame: 'bypass' });
  }
}
