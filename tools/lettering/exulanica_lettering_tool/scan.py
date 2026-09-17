"""The exhaustive scan behind a catalog's cap-height promise.

For every integer cap height from the promised maximum downward, every glyph is scaled to whole
millimetres by the layout's rounding and checked by the ring rule, holes and parts included. The
scan stops at the first size with a failure; that size and the first failing glyph (in character
order) go into the catalog. The promise holds only if that size is below the promised minimum, so
every size in the promise has been checked. Sizes are checked in parallel blocks, but the answer is
the largest failing size and its first failing glyph, which no block order or process count
changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor

from exulanica_lettering_tool.geometry import parts_problem, scale
from exulanica_lettering_tool.outline import GlyphParts

_BLOCK = 50


def _scaled(parts: GlyphParts, cap_height_mm: int, cap_height: int) -> GlyphParts:
    def ring(points: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
        return tuple(
            (scale(x, cap_height_mm, cap_height), scale(y, cap_height_mm, cap_height))
            for x, y in points
        )

    return tuple((ring(outer), tuple(ring(hole) for hole in holes)) for outer, holes in parts)


def first_failure(
    glyphs: list[tuple[str, GlyphParts]], cap_height_mm: int, cap_height: int
) -> str | None:
    for character, parts in glyphs:
        problem = parts_problem(_scaled(parts, cap_height_mm, cap_height))
        if problem:
            return f"{character!r} {problem}"
    return None


def _block(job: tuple[list[tuple[str, GlyphParts]], int, int, int]) -> tuple[int, str] | None:
    glyphs, high, low, cap_height = job
    for size in range(high, low - 1, -1):
        failure = first_failure(glyphs, size, cap_height)
        if failure:
            return size, failure
    return None


def _blocks(maximum: int) -> Iterator[tuple[int, int]]:
    high = maximum
    while high >= 1:
        low = max(1, high - _BLOCK + 1)
        yield high, low
        high = low - 1


def largest_failing_size(
    glyphs: list[tuple[str, GlyphParts]], maximum_mm: int, cap_height: int, workers: int
) -> tuple[int, str | None]:
    """The largest cap height in 1..maximum at which some glyph fails, and why; ``(0, None)`` if none."""
    jobs = [(glyphs, high, low, cap_height) for high, low in _blocks(maximum_mm)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_block, job) for job in jobs]
        try:
            for future in futures:
                found = future.result()
                if found is not None:
                    return found
        finally:
            for future in futures:
                future.cancel()
    return 0, None
