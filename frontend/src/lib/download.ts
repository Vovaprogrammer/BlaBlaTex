export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export function downloadFilename(disposition: string | null, fallback: string): string {
  // Сервер передаёт UTF-8 имя последним параметром, после запасного имени в кавычках.
  const encoded = disposition?.match(/;\s*filename\*=UTF-8''([^;\s]+)\s*$/i)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded);
    } catch {
      // Если имя закодировано неверно, используем запасное.
    }
  }
  return disposition?.match(/;\s*filename="([^"]+)"/i)?.[1] ?? fallback;
}
