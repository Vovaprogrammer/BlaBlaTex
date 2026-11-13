# BlaBlaTex на своём компьютере

Обычно BlaBlaTex открывают на сайте вуза — ставить ничего не нужно. Эта инструкция — для тех, кто хочет работать без сервера: на пилоте, на показе или просто у себя. Всё работает на вашем компьютере, проекты никуда не уходят.

Администратору вуза — [`docs/deploy.md`](deploy.md).

## Что нужно

- **Docker Desktop** — [Windows](https://docs.docker.com/desktop/setup/install/windows-install/), [macOS](https://docs.docker.com/desktop/setup/install/mac-install/), [Linux](https://docs.docker.com/desktop/setup/install/linux/). На Linux подойдёт и Docker Engine с плагином compose. Версия нужна свежая: старый Docker не умеет ставить приложение прямо из реестра (`oci://`).
- **Около 12 ГБ на диске.** Компилятор LaTeX — полный TeX Live, его образ весит около 9 ГБ; остальное — около 1,6 ГБ, плюс ваши проекты. Скачивается при первой установке около 3 ГБ.
- **Память:** BlaBlaTex в покое занимает около 0,5 ГБ, сборка PDF — до 2 ГБ сверху. Настроек Docker Desktop по умолчанию хватает.
- **Mac с процессором Apple (M1 и новее):** образы BlaBlaTex собраны для Intel, Docker Desktop запускает их через Rosetta. В Docker Desktop: Settings → General → «Use Rosetta for x86_64/amd64 emulation on Apple Silicon» — включено. Сборка PDF на таком Mac медленнее, чем на Intel; насколько — мы пока не замеряли.

## Установка

1. Запустите Docker Desktop и дождитесь, пока он напишет, что Docker работает.
2. Откройте терминал: на Windows — PowerShell, на macOS — «Терминал».
3. Выполните одну команду:

```bash
docker compose -f oci://ghcr.io/vovaprogrammer/blablatex:latest up -d --wait -y
```

Команда скачает BlaBlaTex, сама создаст пароль базы и ключ шифрования и запустит всё. Первый раз это занимает несколько минут — в основном скачивание. Готово, когда команда вернула терминал без ошибки.

4. Откройте **http://localhost:8765** и зарегистрируйтесь. Почта — любая: письма BlaBlaTex не отправляет, аккаунт живёт только на вашем компьютере.

Сайт открывается только с этого компьютера: из сети кафе или общежития его не видно.

BlaBlaTex запускается сам вместе с Docker Desktop. Остановить — `docker compose -p blablatex-app stop`, запустить снова — команда установки.

## Агент через MCP

Агент (Claude Code, Codex, Cursor, opencode) работает с BlaBlaTex по личному токену.

1. Создайте токен. Страница токенов на сайте появится в следующих версиях; пока токен создают запросом после входа — раздел «Токен» в [`docs/api.md`](api.md). Адрес API на вашем компьютере — `http://localhost:8765/api/v1`.
2. Подключите агента: адрес BlaBlaTex — `http://localhost:8765`, токен — созданный выше. Пошаговая инструкция для каждого агента будет в `docs/mcp.md` вместе с пакетом MCP.

С VPN тоже работает: запросы агента к BlaBlaTex не уходят с компьютера, а VPN нужен только самому агенту для связи с его моделью. Если агент при включённом VPN не может достучаться до `http://localhost:8765`, проверьте в настройках VPN, что `localhost` не идёт через прокси.

## ИИ в чате на сайте

Агенту через MCP ключ ИИ не нужен: текст пишет его модель. А чату на сайте нужен провайдер ИИ.

1. Создайте в любой папке файл `.env` с настройками провайдера — формат и пример в [`.env.example`](../.env.example), раздел «LLM». JSON заключите в одинарные кавычки:

```bash
LLM_PROVIDERS='{"openrouter":{"base_url":"https://openrouter.ai/api/v1","api_key":"<ключ>","models":{…}}}'
LLM_DEFAULT_PROVIDER=openrouter
```

2. В этой папке выполните команду установки с `--env-file .env`:

```bash
docker compose --env-file .env -f oci://ghcr.io/vovaprogrammer/blablatex:latest up -d --wait -y
```

Ключ остаётся только в этом файле и в контейнерах на вашем компьютере.

## Обновление

Та же команда установки. Она скачает новую версию и перезапустит BlaBlaTex; проекты, файлы и аккаунты сохранятся. Если ставили с `--env-file .env`, добавьте его и сюда.

## Удалить всё

Вместе с проектами и аккаунтами, без возврата. Нужные проекты сначала выгрузите архивом на сайте.

```bash
docker compose -p blablatex-app down -v --rmi all
```

## Если не получилось

| Что видно | Что сделать |
|---|---|
| `Cannot connect to the Docker daemon`, `error during connect`, `dockerDesktopLinuxEngine` | Docker Desktop не запущен или ещё стартует. Запустите и повторите команду. |
| `unknown flag: -y` или `oci://` не понимает | Старый Docker. Обновите Docker Desktop. |
| `port is already allocated`, `bind: address already in use` | Порт 8765 занят другой программой. Выберите другой: в PowerShell `$env:BBT_PORT=8766`, в macOS и Linux `export BBT_PORT=8766`, потом команда установки. Сайт будет на `http://localhost:8766`. |
| `Pool overlaps with other one on this address space` | Подсеть 10.255.255.0/28 уже занята другой сетью Docker или VPN. Задайте другую так же, как порт: `BBT_EDGE_SUBNET=10.255.254.0/28`. |
| Не скачиваются `postgres` или `redis` (`403`, `TLS handshake timeout`) | Они берутся с Docker Hub, а он бывает недоступен из России. Повторите с включённым VPN — нужен он только на время скачивания. |
| `no space left on device` | Не хватает места: освободите около 12 ГБ или увеличьте диск Docker Desktop в Settings → Resources. |
