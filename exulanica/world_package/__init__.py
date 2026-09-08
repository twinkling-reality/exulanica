"""World Memory Package v1 projection and independent verification."""

from typing import Any

from exulanica.world_package.diff import PackageDiff, diff_packages
from exulanica.world_package.package import (
    PROFILE_VERSION,
    PackageError,
    ProhibitedContentError,
    VerificationReport,
    import_check_package,
    inspect_package,
    verify_package,
)


def __getattr__(name: str) -> Any:
    # Projection needs PostgreSQL. Merely importing the offline verifier must not load it.
    if name in {"ProjectionResult", "project_world_package"}:
        from exulanica.world_package import projector

        return getattr(projector, name)
    raise AttributeError(name)


__all__ = [
    "PROFILE_VERSION",
    "PackageDiff",
    "PackageError",
    "ProhibitedContentError",
    "ProjectionResult",
    "VerificationReport",
    "diff_packages",
    "import_check_package",
    "inspect_package",
    "project_world_package",
    "verify_package",
]
