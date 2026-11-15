-- ЛР 2. База данных библиотеки: таблицы и тестовые данные (SQLite).

CREATE TABLE readers (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    ticket TEXT NOT NULL UNIQUE
);

CREATE TABLE books (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    year INTEGER CHECK (year BETWEEN 1800 AND 2030)
);

CREATE TABLE loans (
    id INTEGER PRIMARY KEY,
    reader_id INTEGER NOT NULL REFERENCES readers (id),
    book_id INTEGER NOT NULL REFERENCES books (id),
    taken TEXT NOT NULL,
    due TEXT NOT NULL,
    returned TEXT
);

INSERT INTO readers (id, full_name, ticket) VALUES
    (1, 'Орлова Е. В.', 'Ч-1041'),
    (2, 'Белов К. Д.', 'Ч-1042'),
    (3, 'Савина М. А.', 'Ч-1043'),
    (4, 'Гусев П. Р.', 'Ч-1044');

INSERT INTO books (id, title, author, year) VALUES
    (1, 'Алгоритмы на графах', 'Лебедев', 2019),
    (2, 'Сети ЭВМ', 'Лебедев', 2021),
    (3, 'Основы SQL', 'Миронова', 2018),
    (4, 'Операционные системы', 'Карпов', 2020),
    (5, 'Дискретная математика', 'Миронова', 2017),
    (6, 'Компиляторы', 'Карпов', 2022);

INSERT INTO loans (id, reader_id, book_id, taken, due, returned) VALUES
    (1, 1, 1, '2026-09-02', '2026-09-30', '2026-09-28'),
    (2, 1, 3, '2026-10-01', '2026-10-29', NULL),
    (3, 2, 2, '2026-09-15', '2026-10-13', NULL),
    (4, 3, 1, '2026-10-05', '2026-11-02', '2026-10-30'),
    (5, 3, 4, '2026-10-20', '2026-11-17', NULL),
    (6, 1, 5, '2026-10-21', '2026-11-18', NULL),
    (7, 2, 3, '2026-08-10', '2026-09-07', '2026-09-20');
