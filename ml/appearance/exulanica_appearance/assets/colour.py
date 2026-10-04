"""Palette colours as a piece's vertex colours, exactly, and the nearest swatch to a model's colour.

glTF vertex colours (``COLOR_0``) are linear, and a palette swatch is an 8-bit sRGB colour. A piece
stores each swatch as ``VEC4`` ``UNSIGNED_SHORT`` normalized: the first three channels are the
swatch's channels through one table, the fourth is 65535. The table is the sRGB transfer function
of IEC 61966-2-1 (c/12.92 at or below 0.04045, else ((c + 0.055)/1.055)^2.4, with c = byte/255),
scaled to 65535 and rounded half to even. It is committed once, at :data:`TABLE_PATH`, and both
this writer and the page's loader read that file rather than each computing the formula, so the
two can never round apart. :func:`linear16_table` is how the file was made and what the tests hold
it to.

Every one of the 256 values is distinct, so a stored triple names exactly one sRGB colour and the
page maps it back to its swatch by equality.

Snapping a model's colour to the nearest swatch is done in OKLab (Björn Ottosson, 2020), where
distance follows what a person sees better than in sRGB; a tie goes to the swatch listed first.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from typing import Final

import numpy as np

from exulanica_appearance.canonical import Refused, canonical_bytes, parse_canonical, sha256_hex

__all__ = [
    "TABLE_PATH",
    "TABLE_PROFILE",
    "linear16_table",
    "nearest_swatch",
    "read_table",
    "table_document",
]

TABLE_PROFILE: Final = "exulanica.srgb8-linear16/v1"
#: Relative to the repository root.
TABLE_PATH: Final = "assets/colour/srgb8-linear16.v1.json"
_RULE: Final = (
    "values[c] = round_half_even(65535 * L(c / 255)) for each sRGB byte c, where L is the "
    "IEC 61966-2-1 sRGB transfer function: L(v) = v / 12.92 when v <= 0.04045, else "
    "((v + 0.055) / 1.055) ^ 2.4"
)


def linear16_table() -> tuple[int, ...]:
    """The 256 values, computed in decimal at 50 digits so no binary rounding enters."""
    values = []
    with localcontext() as context:
        context.prec = 50
        for byte in range(256):
            v = Decimal(byte) / Decimal(255)
            if v <= Decimal("0.04045"):
                linear = v / Decimal("12.92")
            else:
                linear = ((v + Decimal("0.055")) / Decimal("1.055")) ** Decimal("2.4")
            scaled = (linear * Decimal(65535)).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)
            values.append(int(scaled))
    return tuple(values)


def table_document() -> dict[str, object]:
    return {"profile": TABLE_PROFILE, "rule": _RULE, "values": list(linear16_table())}


def read_table(repository: Path) -> tuple[tuple[int, ...], str]:
    """The committed table and its sha256, refused unless it is exactly the rule's values."""
    raw = (repository / TABLE_PATH).read_bytes()
    document = parse_canonical(raw.rstrip(b"\n"), TABLE_PATH)
    if document != table_document():
        raise Refused(f"{TABLE_PATH} is not the {TABLE_PROFILE} table its rule states")
    return tuple(document["values"]), sha256_hex(raw)


def table_bytes() -> bytes:
    """The file's bytes: canonical JSON and one newline."""
    return canonical_bytes(table_document()) + b"\n"


def _oklab(srgb8: np.ndarray) -> np.ndarray:
    """OKLab coordinates of 8-bit sRGB colours, shape (n, 3)."""
    v = srgb8.astype(np.float64) / 255.0
    linear = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
    m1 = np.array(
        [
            [0.4122214708, 0.5363325363, 0.0514459929],
            [0.2119034982, 0.6806995451, 0.1073969566],
            [0.0883024619, 0.2817188376, 0.6299787005],
        ]
    )
    m2 = np.array(
        [
            [0.2104542553, 0.7936177850, -0.0040720468],
            [1.9779984951, -2.4285922050, 0.4505937099],
            [0.0259040371, 0.7827717662, -0.8086757660],
        ]
    )
    return np.cbrt(linear @ m1.T) @ m2.T


def nearest_swatch(colours: np.ndarray, palette: Sequence[Sequence[int]]) -> np.ndarray:
    """For each 8-bit sRGB colour (n, 3), the index of the nearest palette swatch in OKLab."""
    if len(palette) == 0:
        raise Refused("a palette holds at least one swatch")
    swatches = _oklab(np.asarray(palette, dtype=np.int64))
    points = _oklab(np.asarray(colours, dtype=np.int64).reshape(-1, 3))
    distances = ((points[:, None, :] - swatches[None, :, :]) ** 2).sum(axis=2)
    # argmin returns the first of equal minima: a tie goes to the swatch listed first.
    return np.argmin(distances, axis=1)
