"""One evidence-to-package frontier demonstration, composed from existing public boundaries.

:func:`run_frontier_demonstration` runs ingest, Selection, reviewed world repositories,
and the WMP projector in order. The receipt is a directory of facts those systems
produced, not a second ledger. :mod:`exulanica.orchestration.manifest` pins the build
profile that demonstration reads.
"""

from exulanica.orchestration.demonstration import (
    FrontierDemonstrationError,
    run_frontier_demonstration,
)
from exulanica.orchestration.manifest import (
    BUILD_PROFILE,
    BuildManifest,
    BuildManifestError,
    load_build_manifest,
)

__all__ = [
    "BUILD_PROFILE",
    "BuildManifest",
    "BuildManifestError",
    "FrontierDemonstrationError",
    "load_build_manifest",
    "run_frontier_demonstration",
]
