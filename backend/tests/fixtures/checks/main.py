"""Методы поиска в массиве: линейный и бинарный поиск, замер времени.

Пример материала студента для тестов проверок (docs/checks.md, «Проект для примеров»).
"""

import random
import sys
import time


def linear_search(items, target):
    """Индекс target в items или -1, если элемента нет."""
    for index, value in enumerate(items):
        if value == target:
            return index
    return -1


def binary_search(items, target):
    """Индекс target в отсортированном items или -1, если элемента нет."""
    low = 0
    high = len(items) - 1
    while low <= high:
        middle = (low + high) // 2
        if items[middle] == target:
            return middle
        if items[middle] < target:
            low = middle + 1
        else:
            high = middle - 1
    return -1


def measure(search, items, target, repeats):
    """Среднее время одного поиска в секундах."""
    started = time.perf_counter()
    result = -1
    for _ in range(repeats):
        result = search(items, target)
    elapsed = (time.perf_counter() - started) / repeats
    return result, elapsed


def make_array(size, seed):
    """Отсортированный массив из size разных чисел."""
    generator = random.Random(seed)
    values = generator.sample(range(size * 10), size)
    values.sort()
    return values


def report(name, index, seconds):
    """Строка вывода: имя метода, индекс и время."""
    print(f"{name}: индекс {index}, {seconds:.4f} с")


def run(size, repeats):
    """Замер обоих методов на массиве из size элементов."""
    items = make_array(size, seed=size)
    # Ищем элемент с индексом 7: он есть в массиве любого размера.
    target = items[7]
    print(f"Массив из {size} элементов")
    index, seconds = measure(linear_search, items, target, repeats)
    report("Линейный поиск", index, seconds)
    index, seconds = measure(binary_search, items, target, repeats)
    report("Бинарный поиск", index, seconds)


def parse_sizes(arguments):
    """Размеры массивов из командной строки, по умолчанию 1000 и 10000."""
    if not arguments:
        return [1000, 10000]
    return [int(argument) for argument in arguments]


def main():
    """Точка входа: замер на всех размерах."""
    sizes = parse_sizes(sys.argv[1:])
    for size in sizes:
        run(size, repeats=100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
