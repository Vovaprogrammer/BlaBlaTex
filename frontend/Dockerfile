# Образ сайта (architecture.md 10, 13): собранный фронт и Caddy, который отдаёт его и
# пропускает /api к API. Отпечатки закрепляют конкретные сборки базовых образов.
FROM node:24.22.1-alpine@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53 AS build

WORKDIR /app
# pnpm той версии, что в packageManager из package.json.
RUN corepack enable
# Сначала только зависимости: этот слой пересобирается, лишь когда меняется lock-файл.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build
# CSP сайта (Caddyfile) пускает встроенные скрипты index.html только по отпечатку sha256.
# Поменяли такой скрипт и забыли про отпечаток — сайт молча его не выполнит; лучше упасть здесь.
RUN node --input-type=module <<'EOF'
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

const html = readFileSync('dist/index.html', 'utf8');
const caddyfile = readFileSync('Caddyfile', 'utf8');
for (const [, attributes, code] of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)) {
  // Внешние скрипты (src=) разрешены как свои, а данные (type="application/json") CSP не трогает.
  const type = /\stype=["']?([^"'\s>]+)/.exec(attributes)?.[1] ?? 'text/javascript';
  if (/\ssrc=/.test(attributes) || !['module', 'text/javascript'].includes(type)) continue;
  // Браузер считает отпечаток после разбора HTML, а разбор сводит переводы строк к \n:
  // в рабочей копии на Windows они \r\n.
  const text = code.replace(/\r\n?/g, '\n');
  const hash = `'sha256-${createHash('sha256').update(text).digest('base64')}'`;
  if (!caddyfile.includes(hash)) {
    console.error(`В CSP из frontend/Caddyfile нет отпечатка встроенного скрипта index.html: ${hash}`);
    process.exit(1);
  }
}
EOF

FROM caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0

COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
