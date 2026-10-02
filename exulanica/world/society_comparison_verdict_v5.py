"""Read a living town's day, scored under the fifth score, with the established anchored verdict.

A day's terms are the fourth score's over the day (:mod:`exulanica.world.society_score_v5`), so
this reader holds them to the day and to the fourth score's need identity, then asks the fourth
score's reader (:mod:`exulanica.world.society_comparison_verdict_v4`), which reuses the third
version's anchored math, to score them and say the verdict. Every module either reads stays byte for
byte as the bindings that name it recorded it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from exulanica.world import society_score_v4, society_score_v5
from exulanica.world.society_catalogs import PERSON_SCORE_CATALOG, ComparisonCatalogs
from exulanica.world.society_comparison_verdict import ComparisonRefused, Reading
from exulanica.world.society_comparison_verdict_v4 import (
    read_comparison as read_fourth_comparison,
)

__all__ = ["read_comparison"]


def read_comparison(
    definition: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    catalogs: ComparisonCatalogs,
    *,
    binding_held: bool,
) -> Reading:
    """Hold each completed run's terms to its definition's day, the window the definition was held
    to its protocol's by when it was recorded, then read them as the fourth score's: the fifth
    score is the fourth's over a day, assembled from its hours."""
    if int(catalogs.versions[PERSON_SCORE_CATALOG]) != society_score_v5.CATALOG_VERSION:
        raise ComparisonRefused(
            "score_version_unknown", "a day's verdict reads fifth-score catalogs"
        )
    society_score_v5.score(catalogs.score)
    window = int(definition["window_ticks"])
    for run in runs:
        if run.get("status") != "completed":
            continue
        terms = run["outcome"]["terms"]
        society_score_v5.validate_terms(terms)
        if int(terms["ticks"]) != window or society_score_v5.KINDS in terms:
            raise ComparisonRefused(
                "day_terms_not_the_window", "a day's run is scored over its definition's whole day"
            )
    fourth = replace(
        catalogs,
        versions={**catalogs.versions, PERSON_SCORE_CATALOG: society_score_v4.CATALOG_VERSION},
    )
    reading = read_fourth_comparison(definition, runs, fourth, binding_held=binding_held)
    return replace(reading, version=society_score_v5.CATALOG_VERSION)
