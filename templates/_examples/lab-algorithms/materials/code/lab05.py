"""ЛР 5. Поиск подстроки: наивный алгоритм и алгоритм Кнута — Морриса — Пратта.

Запуск: python lab05.py
Результаты: results/lab05_results.csv, results/lab05_loglog.png, вывод — в консоль.
"""

import csv
import platform
import random
import statistics
import time
from pathlib import Path

VARIANT = 7
SEED = 100 + VARIANT
ALPHABET = "abcd"
SIZES = [1000, 2000, 4000, 8000, 16000]
REPEATS = 5


def naive_search(text: str, pattern: str) -> tuple[list[int], int]:
    """Все вхождения pattern в text и число сравнений символов."""
    n, m = len(text), len(pattern)
    found, comparisons = [], 0
    for i in range(n - m + 1):
        j = 0
        while j < m:
            comparisons += 1
            if text[i + j] != pattern[j]:
                break
            j += 1
        if j == m:
            found.append(i)
    return found, comparisons


def prefix_function(pattern: str) -> list[int]:
    """pi[i] — длина наибольшего собственного префикса pattern[:i + 1], который
    одновременно является его суффиксом."""
    pi = [0] * len(pattern)
    k = 0
    for i in range(1, len(pattern)):
        while k > 0 and pattern[i] != pattern[k]:
            k = pi[k - 1]
        if pattern[i] == pattern[k]:
            k += 1
        pi[i] = k
    return pi


def kmp_search(text: str, pattern: str) -> tuple[list[int], int]:
    """Все вхождения pattern в text по КМП и число сравнений символов текста."""
    m = len(pattern)
    if m == 0:
        return list(range(len(text) + 1)), 0
    pi = prefix_function(pattern)
    found, comparisons, k = [], 0, 0
    for i, ch in enumerate(text):
        while True:
            comparisons += 1
            if ch == pattern[k]:
                k += 1
                break
            if k == 0:
                break
            k = pi[k - 1]
        if k == m:
            found.append(i - m + 1)
            k = pi[k - 1]
    return found, comparisons


def make_inputs(n: int, rng: random.Random) -> dict[str, tuple[str, str]]:
    """Два класса входов: случайный текст и худший случай для наивного поиска.
    Длина образца — n / 20."""
    m = n // 20
    random_text = "".join(rng.choice(ALPHABET) for _ in range(n))
    start = rng.randrange(n - m)
    random_pattern = random_text[start : start + m]
    worst_text = "a" * n
    worst_pattern = "a" * (m - 1) + "b"
    return {
        "случайный": (random_text, random_pattern),
        "худший": (worst_text, worst_pattern),
    }


def median_ms(search, text: str, pattern: str) -> float:
    """Медиана времени поиска в миллисекундах: один прогрев и REPEATS замеров."""
    search(text, pattern)
    times = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        search(text, pattern)
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times)


def self_check(rng: random.Random) -> None:
    """Сверка обоих алгоритмов со str.find и граничные случаи."""
    for _ in range(300):
        text = "".join(rng.choice("ab") for _ in range(rng.randrange(0, 60)))
        pattern = "".join(rng.choice("ab") for _ in range(rng.randrange(1, 6)))
        expected, i = [], text.find(pattern)
        while i != -1:
            expected.append(i)
            i = text.find(pattern, i + 1)
        assert naive_search(text, pattern)[0] == expected
        assert kmp_search(text, pattern)[0] == expected
    assert kmp_search("", "a")[0] == [] and naive_search("", "a")[0] == []
    assert kmp_search("ab", "abc")[0] == [] and naive_search("ab", "abc")[0] == []
    assert kmp_search("aaaa", "aa")[0] == [0, 1, 2] == naive_search("aaaa", "aa")[0]
    print("self_check: 300 случайных входов и 3 граничных случая, расхождений с str.find нет")


def main() -> None:
    rng = random.Random(SEED)
    print(f"Вариант {VARIANT}, seed {SEED}, Python {platform.python_version()}")
    self_check(rng)
    rows = []
    for n in SIZES:
        for kind, (text, pattern) in make_inputs(n, rng).items():
            for name, search in (("naive", naive_search), ("kmp", kmp_search)):
                ms = median_ms(search, text, pattern)
                comparisons = search(text, pattern)[1]
                rows.append((n, kind, name, round(ms, 3), comparisons))
                print(f"n={n:6d} {kind:9s} {name:5s} {ms:9.3f} мс {comparisons:9d} сравнений")
    out = Path("results")
    out.mkdir(exist_ok=True)
    with open(out / "lab05_results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["n", "text", "algorithm", "median_ms", "comparisons"])
        writer.writerows(rows)
    plot(rows, out / "lab05_loglog.png")


def plot(rows: list[tuple], path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    for kind, style in (("случайный", "-"), ("худший", "--")):
        for name, marker in (("naive", "o"), ("kmp", "s")):
            points = [(n, ms) for n, k, a, ms, _ in rows if k == kind and a == name]
            ax.loglog(*zip(*points), style, marker=marker, label=f"{name}, {kind}")
    ax.set_xlabel("Длина текста n")
    ax.set_ylabel("Время, мс")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=110)


if __name__ == "__main__":
    main()
