"""Environment and local-path resolution for the Exulanica namespace.

Every deployment setting is read through :func:`env_get` as ``EXULANICA_{suffix}``.
The pre-release Orimera names are withdrawn. ADR-0011 records why.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

__all__ = [
    "CONTAINER_DATA_DIR",
    "DEFAULT_BRIEFS_DIR",
    "DEFAULT_CORPUS_DIR",
    "DEFAULT_DATA_DIR",
    "LEGACY_BRIEFS_DIR",
    "env_get",
    "env_name",
    "resolve_briefs_path",
    "resolve_corpus_dir",
    "resolve_data_dir",
]

_PREFIX: Final = "EXULANICA_"

DEFAULT_DATA_DIR: Final = Path(".exulanica/local")
CONTAINER_DATA_DIR: Final = Path("/var/lib/exulanica")
DEFAULT_CORPUS_DIR: Final = Path(".exulanica/media/intake/synthetic")
DEFAULT_BRIEFS_DIR: Final = Path(".exulanica/briefs")
LEGACY_BRIEFS_DIR: Final = Path(".orimera/briefs")


def env_name(suffix: str) -> str:
    """Canonical ``EXULANICA_{suffix}`` name."""
    return f"{_PREFIX}{suffix}"


def env_get(
    suffix: str,
    environ: Mapping[str, str] | None = None,
    default: str | None = None,
) -> str | None:
    """Read ``EXULANICA_{suffix}``. An empty string is treated as unset."""
    environ = os.environ if environ is None else environ
    value = environ.get(env_name(suffix))
    if value is None or value == "":
        return default
    return value


def resolve_data_dir(
    environ: Mapping[str, str] | None = None,
    *,
    explicit: str | Path | None = None,
) -> Path:
    """Resolve the content-addressed store directory.

    An explicit CLI path wins. Otherwise ``EXULANICA_DATA_DIR``. When that is
    unset the default is ``.exulanica/local``. This does not look at ``.orimera``.
    """
    if explicit is not None and str(explicit):
        return Path(explicit)
    configured = env_get("DATA_DIR", environ)
    return Path(configured) if configured else DEFAULT_DATA_DIR


def resolve_corpus_dir(*, explicit: str | Path | None = None) -> Path:
    """Resolve the synthetic-corpus directory."""
    if explicit is not None and str(explicit):
        return Path(explicit)
    return DEFAULT_CORPUS_DIR


def resolve_briefs_path(
    *parts: str,
    root: str | Path | None = None,
    explicit: str | Path | None = None,
) -> Path:
    """Resolve a private operator-notes path under ``.exulanica/briefs``.

    An explicit path wins. Otherwise the current tree is used when it exists,
    or when the legacy ``.orimera/briefs`` tree does not. Existing notes stay
    readable until they are copied. This does not move or delete either tree.
    """
    if explicit is not None and str(explicit):
        return Path(explicit)
    base = Path(root) if root is not None else Path()
    current = base.joinpath(DEFAULT_BRIEFS_DIR, *parts)
    legacy = base.joinpath(LEGACY_BRIEFS_DIR, *parts)
    if current.exists() or not legacy.exists():
        return current
    return legacy
