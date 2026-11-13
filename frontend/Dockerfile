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

FROM caddy:2.11.9-alpine@sha256:003a97808e781aa9f7e75cc2f43d34d461099031faf5e20faefb9f61126836f0

COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
