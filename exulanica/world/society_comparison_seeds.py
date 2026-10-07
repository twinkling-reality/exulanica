"""Which seeds catalog a new comparison is defined under, kept apart from the drawing code.

A comparison's seeds are committed in the seeds catalog (``society-comparison-seeds``), one version
a file, and every judged comparison spends its held-out seeds, so a new judged comparison usually
needs a new version. What a stored run drawing shows never depends on it: a drawing is made from
the run's plan, its stored requests and receipts and its outcome, and names no seed
(:func:`~exulanica.world.society_comparison_result.replay_document`). So the seeds catalog's files
are left out of the drawing digest's data
(:func:`~exulanica.world.society_comparison_drawing.drawing_data`) and the versions below live in
this module, which no drawing module's replay executes and the digest does not cover: a new seeds
version is a new file and a change here, and stored drawings stay current.
``tests/test_comparison_drawing.py`` holds a replay and its drawing to reading no comparison
catalog.
"""

from __future__ import annotations

from typing import Final

__all__ = ["COMPARISON_SEEDS_CATALOG", "DAY_SEEDS_VERSION", "HOUR_SEEDS_VERSION"]

#: The seeds catalog's id, which its files are named by.
COMPARISON_SEEDS_CATALOG: Final = "society-comparison-seeds"
#: The seeds a new comparison over an hour is defined under: the fifth, whose development text is
#: committed and whose held-out seeds a judged comparison of a town's hour spent.
HOUR_SEEDS_VERSION: Final = 5
#: The seeds a new comparison over a day is defined under: the sixth, made for comparisons over a
#: day with development entries the fifth's and held-out seeds of its own.
DAY_SEEDS_VERSION: Final = 6
