"""The control picture a creature's concept follows, and the words it is drawn from.

The control picture is the plan's sketch drawn by :data:`CONTROL_CAMERA` as a depth picture: nearer
is lighter, from white at the sketch's nearest point to a quarter grey at its farthest, the
background black, the same grey in all three channels, as the union control's depth mode reads.
The concept picture's words are the recipe's appearance words and its colour words by role inside
one fixed framing sentence, with no numeral (a model paints the numbers it is told) and no name of
any kind of body: what the body is comes from the control picture. The sentence names nothing to
stand on, as a model asked for a sculpture draws its plinth and a mesh made from that is not the
body.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import Final

import numpy as np

from exulanica_appearance.creatures.geometry import CONTROL_CAMERA, Drawn, rasterise

__all__ = ["CONTROL_PX", "FRAMING", "concept_prompt", "control_picture", "depth_picture"]

#: The control picture's side in pixels, the concept picture's own size.
CONTROL_PX: Final = 1024
#: The framing sentence the appearance words and the colours by role are set in.
FRAMING: Final = (
    "A single whole figure of {appearance}, its body {body} with a {belly} underside, {accent} "
    "markings and {eyes} eyes, seen from the front left and a little above, its whole body in view, "
    "alone against a plain white background, evenly lit, in the style of a painted figure."
)
#: The grey of the farthest drawn point; the nearest is white.
_FARTHEST: Final = 64


def concept_prompt(appearance: str, colour_words: Mapping[str, str]) -> str:
    """The concept picture's words for a recipe's appearance words and its colours by role."""
    words = [appearance, *colour_words.values()]
    if any(character.isdigit() for text in words for character in text):
        raise ValueError("the words hold no numeral")
    return FRAMING.format(appearance=appearance.strip().rstrip("."), **colour_words)


def depth_picture(drawn: Drawn) -> np.ndarray:
    """A drawn view's depth as an 8-bit grey picture (H x W x 3): nearer lighter, empty black."""
    depth = drawn.depth
    shown = drawn.mask
    picture = np.zeros(depth.shape, dtype=np.uint8)
    if shown.any():
        near, far = float(np.nanmax(depth)), float(np.nanmin(depth))
        span = max(near - far, 1e-12)
        grey = _FARTHEST + (255 - _FARTHEST) * (depth[shown] - far) / span
        picture[shown] = np.clip(np.rint(grey), _FARTHEST, 255).astype(np.uint8)
    return np.repeat(picture[..., None], 3, axis=2)


def control_picture(sketch: np.ndarray, size: int = CONTROL_PX) -> tuple[bytes, Drawn]:
    """The sketch's triangles (T x 3 x 3, slot frame) as the control picture's PNG, and the drawn
    view, whose framing every later silhouette of this creature is drawn in."""
    from PIL import Image

    drawn = rasterise(sketch, CONTROL_CAMERA, size)
    buffer = io.BytesIO()
    Image.fromarray(depth_picture(drawn), mode="RGB").save(buffer, format="PNG")
    return buffer.getvalue(), drawn
