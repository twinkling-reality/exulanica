"""Read a society of things' sixth-score outcomes with the established anchored verdict math.

The third verdict module stays byte for byte as retained third-score bindings recorded it. This
reader first holds each completed run's sixth-score terms to their shape (the acts, lines and
dropped hands acts they report), then asks that module to compute the same half need-relief, half
variety anchored score and verdict over those exact terms: the variety count the terms carry
already holds each person's acts beside their activities, so the third reader's math is unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from exulanica.world import society_score_v3, society_score_v6
from exulanica.world.society_catalogs import (
    PERSON_SCORE_CATALOG,
    ComparisonCatalogs,
)
from exulanica.world.society_comparison_verdict import (
    ComparisonRefused,
    Reading,
)
from exulanica.world.society_comparison_verdict import (
    read_comparison as read_third_comparison,
)

__all__ = ["read_comparison"]


def read_comparison(
    definition: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    catalogs: ComparisonCatalogs,
    *,
    binding_held: bool,
) -> Reading:
    """Validate sixth-score terms and reuse the third version's score and verdict math."""
    if int(catalogs.versions[PERSON_SCORE_CATALOG]) != society_score_v6.CATALOG_VERSION:
        raise ComparisonRefused(
            "score_version_unknown", "a things verdict requires sixth-score catalogs"
        )
    society_score_v6.score(catalogs.score)
    for run in runs:
        if run.get("status") == "completed":
            society_score_v6.validate_terms(run["outcome"]["terms"])
    variety = catalogs.score[society_score_v3.VARIETY]
    third = ComparisonCatalogs(
        # The third reader is shown the sixth's variety as the count it reads, from the terms.
        score={**catalogs.score, society_score_v3.VARIETY: {**variety, "reads": "states"}},
        protocol=catalogs.protocol,
        seeds=catalogs.seeds,
        versions={**catalogs.versions, PERSON_SCORE_CATALOG: society_score_v3.CATALOG_VERSION},
        sha256=catalogs.sha256,
    )
    reading = read_third_comparison(definition, runs, third, binding_held=binding_held)
    return replace(reading, version=society_score_v6.CATALOG_VERSION)
