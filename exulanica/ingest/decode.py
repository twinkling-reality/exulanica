"""Ingest's upright-image facade over the shared bounded sensor decoder.

``exulanica.corpus.decode`` owns every Pillow image-open call, the 64-megapixel budget, and
single-frame refusal. This compatibility module keeps the existing ingest API and applies EXIF
orientation exactly once through ``extract_exif_facts``. Reconstruction uses the lower-level
sensor decoder directly, preserving the pixel grid against which COLMAP cameras were calibrated.
The corpus decoder's module documentation retains the measured memory and warning-filter rationale.
"""

from __future__ import annotations

from PIL import Image

from exulanica.corpus.decode import MAX_PIXELS, UNREADABLE, open_sensor, probe
from exulanica.ingest.exif import ExifFacts, extract_exif_facts

__all__ = ["MAX_PIXELS", "UNREADABLE", "open_upright", "probe"]


def open_upright(data: bytes) -> tuple[Image.Image, ExifFacts]:
    """Return bounded upright pixels and the facts recorded by their original photograph."""
    with open_sensor(data) as opened:
        return extract_exif_facts(opened)
