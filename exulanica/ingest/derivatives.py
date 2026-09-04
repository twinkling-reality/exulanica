"""Downscaled renditions: the only pixels a model ever sees.

**Size.** Image tokens are strongly sub-linear in pixel area: 277 prompt tokens at 256 px and
772 at 768 px, so nine times the area costs 2.8 times the tokens. The instinct to downscale
hard is therefore a false economy. It costs the legible signage that the OCR and the place
proposal both depend on, and it saves a fraction of a cent per thousand photographs. The
rendition is 768 px on the long edge.

**Never upscale.** A small original is sent at its own size. Enlarging it adds tokens and no
information, and it invites a model to read detail that is not there.

**The rendition carries no EXIF.** Two reasons, and the second is the important one:

1.  The pixels are already upright, so a surviving orientation tag would make a viewer rotate
    them a second time.
2.  It is data minimisation with teeth. EXIF is where the GPS fix, the device serial and the
    owner name live. Stripping it means the bytes that leave this machine for an inference
    endpoint contain the photograph and nothing else. The provider does not need the user's
    coordinates to describe a waterfall.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Final

from PIL import Image

from exulanica.ingest.stages import StageSpec

__all__ = ["Rendition", "render"]

_RESAMPLERS: Final = {
    "lanczos": Image.Resampling.LANCZOS,
    "bicubic": Image.Resampling.BICUBIC,
}
#: JPEG subsampling codes. 4:4:4 keeps full chroma resolution, which is what small text in a
#: photographed sign is made of.
_SUBSAMPLING: Final = {"4:4:4": 0, "4:2:2": 1, "4:2:0": 2}


@dataclass(frozen=True, slots=True)
class Rendition:
    """Encoded bytes plus the display geometry every region will be normalised against."""

    data: bytes
    media_type: str
    width: int
    height: int
    downscaled: bool


def render(upright: Image.Image, spec: StageSpec) -> Rendition:
    """Encode the model-input rendition from an already-upright image.

    ``upright`` must be the orientation-normalised image. This function does not look at EXIF
    and must not: orientation is decided once, at intake, and a second decision here is how a
    pipeline ends up applying a rotation twice.
    """
    params = spec.params
    max_edge = int(params["max_edge_px"])
    resample = _RESAMPLERS[str(params["resample"])]
    optimize = params["optimize"]
    if type(optimize) is not bool:
        raise ValueError("rendition optimize parameter must be a boolean")

    image = upright
    if image.mode in {"RGBA", "LA", "P"}:
        # Composite onto white rather than dropping the alpha channel. Discarding alpha leaves
        # whatever happened to be underneath, which for a screenshot is usually black, and a
        # black background changes what the model reports about the scene.
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    longest = max(image.size)
    downscaled = longest > max_edge
    if downscaled:
        scale = max_edge / longest
        target = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(target, resample)

    buffer = io.BytesIO()
    image.save(
        buffer,
        format=str(params["format"]),
        quality=int(params["quality"]),
        subsampling=_SUBSAMPLING[str(params["subsampling"])],
        optimize=optimize,
        # exif is not passed, so none is written. See the module docstring.
    )
    return Rendition(
        data=buffer.getvalue(),
        media_type="image/jpeg",
        width=image.width,
        height=image.height,
        downscaled=downscaled,
    )
