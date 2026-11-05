export type DiffHunk = { oldLine: number; newLine: number; before: string; after: string };

export function parseDiff(diff: string): DiffHunk[] {
  const hunks: DiffHunk[] = [];
  let section: { oldLine: number; newLine: number; before: string[]; after: string[] } | undefined;
  function save() {
    if (!section) return;
    hunks.push({ ...section, before: section.before.join(''), after: section.after.join('') });
  }
  let last: string | undefined;
  // Первые две строки — пути; заголовки фрагментов содержат позиции в исходных файлах.
  for (const line of diff.split('\n').slice(2)) {
    const header = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
    if (header) {
      save();
      section = { oldLine: Number(header[1]), newLine: Number(header[2]), before: [], after: [] };
      continue;
    }
    if (!section) continue;
    const prefix = line[0];
    if (prefix === '\\') {
      // Служебная строка относится только к предшествующей строке diff.
      if (last !== '+') trimNewline(section.before);
      if (last !== '-') trimNewline(section.after);
    }
    if (prefix === ' ' || prefix === '-') section.before.push(line.slice(1) + '\n');
    if (prefix === ' ' || prefix === '+') section.after.push(line.slice(1) + '\n');
    last = prefix;
  }
  save();
  return hunks;
}

function trimNewline(lines: string[]) {
  if (lines.length) lines[lines.length - 1] = lines[lines.length - 1]!.slice(0, -1);
}
