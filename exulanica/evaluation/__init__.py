"""What a number from this harness may say, and what it may not.

``docs/evaluation-methodology.md`` is the specification and section 3 is the part that governs
this package: nine mechanically enforceable rules about what may be claimed from a measurement,
and an overclaiming checklist that is a review gate on external copy. The rules that can be
enforced by code are enforced here rather than trusted to whoever writes the summary.

**This package sits ABOVE the HTTP API and it is the only thing that does.** M10 specifies its
authorisation sweep as "table-driven, generated from the router, so a new route without a test
fails CI", and a harness that cannot see the router hand-enumerates routes. That is not a
hypothetical failure: it happened, when FastAPI stopped flattening included routers and a
one-level walk quietly stopped seeing the entire authenticated surface. So the layering says, in
one sentence: nothing the product runs depends on the API, and the only thing that does is the
thing that measures it.

**The corpus problem, first and loudest.** The question corpus is synthetic:
renders of three geometric arrangements. Nothing about identity, clustering or reconstruction is
real on it. No number computed against it is evidence about photographs, no interval is printed
against it, and the report says all of that above the results rather than in a footnote.
"""

from __future__ import annotations

from exulanica.evaluation.bundle import (
    AccessPurpose,
    AccessReceipt,
    AuthorizedSource,
    CorpusBundle,
    CorpusContractError,
    CorpusItem,
)
from exulanica.evaluation.counts import Count, NamedCase, Sample, render, wilson
from exulanica.evaluation.execution import execution_snapshot
from exulanica.evaluation.ground_truth import Frame, GroundTruth
from exulanica.evaluation.metrics import METRICS, Component
from exulanica.evaluation.provenance import (
    ArchiveError,
    ArchiveReceipt,
    create_archive,
    verify_archive,
)
from exulanica.evaluation.replay import (
    CleanDatabaseError,
    ReplayError,
    ReplayReceipt,
    assert_pristine_database,
    run_clean_replay,
)
from exulanica.evaluation.report import BANNED, banned_words_in, render_report
from exulanica.evaluation.synthetic_pose import (
    SyntheticPoseEvaluation,
    evaluate_synthetic_pose,
)

__all__ = [
    "BANNED",
    "METRICS",
    "AccessPurpose",
    "AccessReceipt",
    "ArchiveError",
    "ArchiveReceipt",
    "AuthorizedSource",
    "CleanDatabaseError",
    "Component",
    "CorpusBundle",
    "CorpusContractError",
    "CorpusItem",
    "Count",
    "Frame",
    "GroundTruth",
    "NamedCase",
    "ReplayError",
    "ReplayReceipt",
    "Sample",
    "SyntheticPoseEvaluation",
    "assert_pristine_database",
    "banned_words_in",
    "create_archive",
    "evaluate_synthetic_pose",
    "execution_snapshot",
    "render",
    "render_report",
    "run_clean_replay",
    "verify_archive",
    "wilson",
]
