"""Per-row and per-column statistics of a final latent, so a line in a decoded tile can be placed.

Session 1 left one open question. Painted render a1 carries a dark band three pixels tall whose dash
period along it is exactly the autoencoder's own 8 px cell pitch, centred on a latent row boundary:
the decoder drew one latent row of cells as dark blobs. What that does not say is whether the latent
already held that row before the decoder saw it, and nothing in the run's own output can answer it
because latents are not retained.

This measures the latent the decoder is about to read: for each row and each column, the mean over
channels, and from those the index that stands furthest out of its own distribution in robust sigma.
A run writes it beside each output. If a decoded line has a latent row standing 8 or more sigma out
at the same index, the latent is where the defect is; if the latent is level there, the decoder or
the crop is. Every value is an integer in thousandths, so the record stays canonical.
"""

from __future__ import annotations

from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from exulanica_appearance.canonical import Refused

__all__ = ["LINE_SIGMA_MILLI", "latent_lines"]

#: A row this far out of its own distribution is a line and not texture: 8 robust sigma, the
#: threshold that separated painted render a1's band from the ordinary variation of all 64 outputs.
LINE_SIGMA_MILLI: Final = 8_000


def _robust(profile: NDArray[np.float64]) -> tuple[NDArray[np.float64], float]:
    middle = float(np.median(profile))
    spread = float(np.median(np.abs(profile - middle))) * 1.4826
    if spread <= 0.0:
        return np.zeros_like(profile), 0.0
    return (profile - middle) / spread, spread


def latent_lines(values: NDArray[np.floating], *, source: str) -> dict[str, Any]:
    """Where the rows and columns of one latent stand out, in thousandths of a robust sigma."""
    array = np.asarray(values, dtype=np.float64)
    array = array.reshape([size for size in array.shape if size != 1])
    if array.ndim != 3:
        raise Refused(
            f"a latent is read as channels by rows by columns; this one is {values.shape}"
        )
    if not source:
        raise Refused("a latent measurement says what it was taken from")
    grid = array.mean(axis=0)
    out: dict[str, Any] = {
        "channels": int(array.shape[0]),
        "columns": int(grid.shape[1]),
        "profile": "exulanica.appearance-latent-lines/v1",
        "rows": int(grid.shape[0]),
        "source": source,
        "value_milli": {
            "max": round(float(array.max()) * 1000),
            "mean": round(float(array.mean()) * 1000),
            "min": round(float(array.min()) * 1000),
        },
    }
    for axis, name in ((1, "row"), (0, "column")):
        scores, spread = _robust(grid.mean(axis=axis))
        worst = int(np.argmax(np.abs(scores)))
        out[name] = {
            "beyond_threshold": int((np.abs(scores) * 1000 >= LINE_SIGMA_MILLI).sum()),
            "index": worst,
            "sigma_milli": round(float(scores[worst]) * 1000),
            "spread_milli": round(spread * 1000),
        }
    return out
