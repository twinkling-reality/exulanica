"""The route backends a generated asset job runs on a rented GPU.

Each needs CUDA and the pinned upstream code the job fetches, so its model libraries are imported
inside its constructor and nothing here is imported by the dry run. ``ROUTES`` names the class
for each route; the stub route lives with the dry run.
"""

from __future__ import annotations

from typing import Final

__all__ = ["ROUTES"]

ROUTES: Final = {
    "A": "exulanica_appearance.assets.backends.trellis:TrellisBackend",
    "B": "exulanica_appearance.assets.backends.step1x:Step1XBackend",
}
