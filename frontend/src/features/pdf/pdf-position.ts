type PdfView = { page: number; offset: number; zoom: 'fit' | number };
export class PdfPosition {
  private value: PdfView = { page: 1, offset: 0, zoom: 'fit' };
  get = () => this.value;
  set = (update: Partial<PdfView>) => {
    this.value = { ...this.value, ...update };
  };
}
export const initialPdfPosition = () => new PdfPosition();
export function clampPage(page: number, count: number) {
  return Math.max(1, Math.min(count || 1, Number.isFinite(page) ? Math.floor(page) : 1));
}
