// Три заранее заданные страницы для проверки прокрутки; это не результат компиляции.
const objects = [
  '<< /Type /Catalog /Pages 2 0 R >>',
  '<< /Type /Pages /Kids [3 0 R 5 0 R 7 0 R] /Count 3 >>',
];
for (let page = 1; page <= 3; page++) {
  const contentId = 2 + page * 2;
  objects.push(
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 9 0 R >> >> /Contents ${contentId} 0 R >>`,
  );
  const stream = `BT /F1 22 Tf 48 770 Td (BlaBlaTex - PDF preview) Tj /F1 12 Tf 0 -38 Td (Demonstration fixture. Not a compiled report.) Tj 0 -28 Td (Page ${page} of 3) Tj ET`;
  objects.push(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
}
objects.push('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
let document = '%PDF-1.4\n';
const offsets = [0];
objects.forEach((object, index) => {
  offsets.push(document.length);
  document += `${index + 1} 0 obj\n${object}\nendobj\n`;
});
const start = document.length;
document += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets
  .slice(1)
  .map((offset) => String(offset).padStart(10, '0') + ' 00000 n \n')
  .join('')}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${start}\n%%EOF\n`;
export const pdfFixture = new TextEncoder().encode(document);
