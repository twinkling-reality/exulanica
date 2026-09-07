"""Fill a person out of a photograph, the same way on every machine.

**Why this is not ``ImageDraw.polygon``.** Pillow's polygon rasteriser is an implementation
detail of Pillow: its edge rule has changed between releases, and this project pins Pillow with a
lower bound rather than an exact version. A derivative whose edge pixels depend on which Pillow
happened to be installed is not a deterministic derivative, and the masked source's digest enters
the scene build inputs, so a rasteriser that drifted would silently invalidate builds that had
already been accepted. The scanline below is written in exact integer arithmetic and belongs to
this repository, so its output is a function of the outline and the image size and nothing else.

**The sampling rule, stated once so it can be relied on.** A pixel is masked when its centre lies
inside the outline under the even-odd rule. The centre of column ``px`` in an image ``w`` wide is
``(2*px + 1) * PPM / (2*w)`` parts per million, compared by cross multiplication so no division is
ever performed and no float ever decides an edge pixel. Spans are half open on the right, so two
outlines sharing an edge tile without a seam and without double covering.

**The outline is grown before it is filled.** A mask cut exactly on a detector's boundary leaves a
rim of the person's own pixels, which is the difference between hiding somebody and outlining
them. The dilation is a fixed number of 3 by 3 integer maximum passes, so it is morphology rather
than a blur and adds no partial coverage anywhere.

**The fill is neutral and it is not inpainting.** A masked area becomes flat mid grey. Nothing is
generated to stand in for the person: a plausible invented background is a claim about what was
behind them, the design note puts generative fill out of scope, and the status line says the area
is blank rather than pretending it was never occupied.
"""

from __future__ import annotations

import io
from fractions import Fraction
from typing import Final

from PIL import Image, ImageFilter

from exulanica.canonical import ceil_div, round_half_down
from exulanica.consent.regions import Silhouette
from exulanica.evidence.region import PPM

__all__ = ["NEUTRAL_FILL", "build_coverage", "encode_masked_source", "mask_image"]

#: Mid grey. Obviously not photographic, carries no detail, and fixed here rather than passed in
#: so two callers cannot produce two different derivatives of one photograph.
NEUTRAL_FILL: Final[tuple[int, int, int]] = (128, 128, 128)


def _crossings(silhouette: Silhouette, y_ppm: int) -> list[Fraction]:
    """Every edge crossing on one scanline, exact and in increasing order.

    ``Fraction`` rather than a pair of integers because these have to be *ordered*, and two
    ratios order by cross multiplication rather than lexicographically by numerator. Sorting the
    pairs directly is the bug this comment exists to stop somebody reintroducing: it puts 1/2
    before 2/5 and fills the complement of the outline.
    """
    found: list[Fraction] = []
    points = silhouette.points
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        if (y1 > y_ppm) == (y2 > y_ppm):
            continue
        found.append(Fraction(x1 * (y2 - y1) + (y_ppm - y1) * (x2 - x1), y2 - y1))
    found.sort()
    return found


def _first_column_at_or_past(value: Fraction, width: int) -> int:
    """The first column whose centre is at or past ``value`` parts per million.

    ``centre(px) >= v`` is ``(2*px + 1) * PPM * v.denominator >= v.numerator * 2 * width``, which
    rearranges to a ceiling division of exact integers with no rounding decision left over.
    """
    return ceil_div(
        value.numerator * 2 * width - PPM * value.denominator,
        2 * PPM * value.denominator,
    )


def build_coverage(
    silhouettes: tuple[Silhouette, ...], width: int, height: int, *, dilation_px: int = 0
) -> Image.Image:
    """An ``L`` mask, 255 where a person is hidden and 0 everywhere else.

    Returned as an image rather than drawn straight onto the photograph so the same coverage
    answers both questions the design asks: which pixels a derivative must blank, and which rays
    a trained Gaussian may not sit on.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"an image must have positive dimensions, got {width}x{height}")
    if dilation_px < 0:
        raise ValueError("dilation cannot be negative; a shrunken mask reveals a rim of a person")
    coverage = bytearray(width * height)
    for silhouette in silhouettes:
        for row in range(height):
            y_ppm = (2 * row + 1) * PPM // (2 * height)
            crossings = _crossings(silhouette, y_ppm)
            offset = row * width
            for index in range(0, len(crossings) - 1, 2):
                start = max(0, _first_column_at_or_past(crossings[index], width))
                end = min(width, _first_column_at_or_past(crossings[index + 1], width))
                if end > start:
                    coverage[offset + start : offset + end] = b"\xff" * (end - start)
    mask = Image.frombytes("L", (width, height), bytes(coverage))
    for _ in range(dilation_px):
        mask = mask.filter(ImageFilter.MaxFilter(3))
    return mask


def mask_image(
    upright: Image.Image, silhouettes: tuple[Silhouette, ...], *, dilation_millionths: int
) -> Image.Image:
    """Return ``upright`` with every outline filled neutral. The input is never modified.

    An empty outline set returns an RGB copy rather than the original object, so a caller cannot
    hold a reference to the source image and believe it was masked.
    """
    image = upright.convert("RGB")
    if not silhouettes:
        return image
    width, height = image.size
    dilation = round_half_down(dilation_millionths * max(width, height), 1_000_000)
    mask = build_coverage(silhouettes, width, height, dilation_px=max(1, dilation))
    return Image.composite(Image.new("RGB", (width, height), NEUTRAL_FILL), image, mask)


def encode_masked_source(image: Image.Image, params: dict[str, object]) -> bytes:
    """Encode the derivative with every encoder setting declared in the stage parameters.

    The settings live in the stage parameters for the reason ``rendition``'s do: a changed quality
    or subsampling changes the bytes, and a change that did not move the stage digest would leave
    two different derivatives sharing one artifact row. No EXIF is written, so the derivative
    carries no capture metadata the original's own record does not already hold.
    """
    buffer = io.BytesIO()
    image.save(
        buffer,
        format=str(params["format"]),
        quality=int(params["quality"]),
        subsampling=str(params["subsampling"]),
        optimize=bool(params["optimize"]),
    )
    return buffer.getvalue()
