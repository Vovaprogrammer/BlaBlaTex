"""Сортировка слиянием с одним буфером на всю сортировку."""


def merge_sort(items: list[int]) -> list[int]:
    # Буфер выделяется один раз, а не на каждом уровне рекурсии.
    buffer = [0] * len(items)
    _sort(items, buffer, 0, len(items))
    return items


def _sort(items: list[int], buffer: list[int], left: int, right: int) -> None:
    if right - left < 16:
        insertion_sort(items, left, right)  # короткие отрезки — вставками
        return
    middle = (left + right) // 2
    _sort(items, buffer, left, middle)
    _sort(items, buffer, middle, right)
    merge(items, buffer, left, middle, right)


def report(sizes: list[int], timings: dict[int, float]) -> None:
    for size in sizes:
        print(f"Длина массива: {size:>9}, время сортировки слиянием: {timings[size]:.3f} мс, медиана из пяти повторов")
