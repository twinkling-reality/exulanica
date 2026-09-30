"""Read a living town's fourth-score outcomes with the established anchored verdict math.

The third verdict module stays byte-for-byte as retained third-score bindings recorded it. This
reader first holds living term identity across the same seed's arms, then asks that module to
compute the same half need-relief, half variety anchored score and verdict over those exact terms.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from exulanica.world import society_score_v4
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
    """Validate fourth-score need identity and reuse the third version's score and verdict math."""
    if int(catalogs.versions[PERSON_SCORE_CATALOG]) != society_score_v4.CATALOG_VERSION:
        raise ComparisonRefused(
            "score_version_unknown", "living verdict requires fourth-score catalogs"
        )
    society_score_v4.score(catalogs.score)
    by_seed: dict[str, dict[str, int]] = {}
    for run in runs:
        if run.get("status") != "completed":
            continue
        terms = run["outcome"]["terms"]
        society_score_v4.validate_terms(terms)
        thresholds = dict(terms["need_thresholds"])
        seed = str(run["seed_digest"])
        if seed in by_seed and by_seed[seed] != thresholds:
            raise ComparisonRefused(
                "living_need_thresholds_changed", "a seed's arms name different need thresholds"
            )
        by_seed[seed] = thresholds
    third = ComparisonCatalogs(
        score=catalogs.score,
        protocol=catalogs.protocol,
        seeds=catalogs.seeds,
        versions={**catalogs.versions, PERSON_SCORE_CATALOG: 3},
        sha256=catalogs.sha256,
    )
    reading = read_third_comparison(definition, runs, third, binding_held=binding_held)
    return replace(reading, version=society_score_v4.CATALOG_VERSION)
