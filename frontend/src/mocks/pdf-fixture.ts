// Заранее заданная пустая PDF-страница для просмотра, не результат компиляции отчёта.
const objects = [
  '<< /Type /Catalog /Pages 2 0 R >>',
  '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
  '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>',
  '<< /Length 0 >>\nstream\n\nendstream',
];
let document = '%PDF-1.4\n';
const offsets = [0];
objects.forEach((object, index) => {
  offsets.push(document.length);
  document += `${index + 1} 0 obj\n${object}\nendobj\n`;
});
const start = document.length;
document += `xref\n0 5\n0000000000 65535 f \n${offsets
  .slice(1)
  .map((offset) => String(offset).padStart(10, '0') + ' 00000 n \n')
  .join('')}trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`;
export const pdfFixture = new TextEncoder().encode(document);
