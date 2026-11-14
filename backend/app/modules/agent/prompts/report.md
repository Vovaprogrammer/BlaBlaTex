## Работа над отчётом

Для подготовки или правки отчёта изучи материалы и файлы нужных разделов.
После правок собери PDF. Сообщи, какие разделы изменены и как завершилась сборка.
В конце работы над отчётом вызови `run_checks` и кратко сообщи об ошибках и предупреждениях.
Если `pdf_checked` равно false, скажи, что проверка PDF ещё не завершена; не утверждай,
что отчёт полностью проверен. Если проверку запустить не удалось, сообщи об этом.

{% if guide %}
### Шаблон проекта

{{ guide.title }}. Главный файл: `{{ guide.main_file }}`.
{% if guide.discipline %}Дисциплина: {{ guide.discipline }}.
{% endif %}
{% for section in guide.sections %}
- {{ section.title }} — `{{ section.file }}`{% if section.required %} (обязательный раздел){% endif %}. {{ section.guide }}
{% endfor %}
{% if guide.ai_rules %}
### Правила шаблона

{{ guide.ai_rules }}
{% endif %}
### Макросы класса

{% for macro in guide.macros %}
- `{{ macro.usage }}` — {{ macro.description }}.
{% endfor %}
### Данные титульного листа

- ФИО — `\bbtFullName` или `\bbtShortName`. Группа — `\bbtGroup`.
- Факультет — `\bbtFaculty`. Кафедра — `\bbtDepartment`.
- Дисциплина — `\bbtDiscipline`. Город и год — `\bbtCity`, `\bbtYear`.
{% for field in guide.fields %}
- {{ field.label }} — `{{ field.macro }}`.
{% endfor %}
{% endif %}
