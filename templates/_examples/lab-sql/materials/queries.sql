-- ЛР 2. Запросы к базе библиотеки. Дата проверки — 2026-11-10.

-- 1. Книги автора Миронова, новые сначала.
SELECT title, year
FROM books
WHERE author = 'Миронова'
ORDER BY year DESC;

-- 2. Книги на руках: читатель, книга, срок возврата.
SELECT r.full_name, b.title, l.due
FROM loans AS l
JOIN readers AS r ON r.id = l.reader_id
JOIN books AS b ON b.id = l.book_id
WHERE l.returned IS NULL
ORDER BY l.due;

-- 3. Сколько раз каждый читатель брал книги; только те, кто брал больше одного раза.
SELECT r.full_name, COUNT(*) AS loans_count
FROM loans AS l
JOIN readers AS r ON r.id = l.reader_id
GROUP BY r.id
HAVING COUNT(*) > 1
ORDER BY loans_count DESC;

-- 4. Просроченные на дату проверки: не возвращены, срок прошёл.
SELECT r.full_name, b.title, l.due,
       julianday('2026-11-10') - julianday(l.due) AS days_late
FROM loans AS l
JOIN readers AS r ON r.id = l.reader_id
JOIN books AS b ON b.id = l.book_id
WHERE l.returned IS NULL AND l.due < '2026-11-10'
ORDER BY days_late DESC;

-- 5. Книги, которые ни разу не брали.
SELECT title, author
FROM books
WHERE id NOT IN (SELECT book_id FROM loans)
ORDER BY title;
