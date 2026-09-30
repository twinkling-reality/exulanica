"""Time a sample town at every point the served specification allows, for the samples' time limit.

    uv run python scripts/measure_world_drafting_samples.py

Reads the specification document as the drafting route reads it, and generates one sample town
(``compute_sample``, the worker's own job, run here in this process) for every combination of the
values a person may set, starting from the first preset. Prints each point's seconds and outcome,
then the p50, p95 and longest, and the time limit the rule derives from the longest: twice it,
rounded up to a whole multiple of 5 s, the rule the model manifest derives a timeout by. Spends
nothing and writes nothing; run it inside ``.exulanica/bin/quiet-slot`` so the figures are not
another process's load.
"""

from __future__ import annotations

import itertools
import json
import math
import sys
import time
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]

#: The rule the model manifest derives a timeout by (``timeout_rule`` in models.manifest.json).
HEADROOM: Final = 2
ROUND_UP_TO_SECONDS: Final = 5


def _percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def main() -> int:
    from exulanica.selection.world_drafting import specification_view
    from exulanica.world.specification_source import served_document
    from exulanica.world.specification_samples import compute_sample, sample_world_id

    view = specification_view(served_document())
    preset = view.presets[0].key
    keys = [entry.key for entry in view.adjustable]
    seconds: list[float] = []
    for combination in itertools.product(*(entry.allowed() for entry in view.adjustable)):
        values = dict(zip(keys, combination, strict=True))
        started = time.perf_counter()
        sample = compute_sample(preset, values, sample_world_id(preset, values, view.sha256))
        took = time.perf_counter() - started
        seconds.append(took)
        print(
            json.dumps(
                {
                    "values": values,
                    "seconds": round(took, 3),
                    "status": sample["status"],
                    "people": sample.get("people"),
                    "vehicles": sample.get("vehicles"),
                    "refused": sample.get("refused") or sample.get("vehicles_refused"),
                }
            ),
            flush=True,
        )
    longest = max(seconds)
    limit = math.ceil(HEADROOM * longest / ROUND_UP_TO_SECONDS) * ROUND_UP_TO_SECONDS
    print(
        json.dumps(
            {
                "specification_sha256": view.sha256,
                "points": len(seconds),
                "p50_s": round(_percentile(seconds, 0.5), 3),
                "p95_s": round(_percentile(seconds, 0.95), 3),
                "longest_s": round(longest, 3),
                "limit_s": limit,
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
