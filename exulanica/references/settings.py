"""How an installation configures references: who plays their jobs, for whom, and each source.

* ``EXULANICA_REFERENCE_WORKER``: absent or on, this process plays reference jobs in a thread;
  ``off`` (or ``0``, ``false``, ``no``), nobody does, and a request is refused before it is queued.
  There is no separate process: a reference job is short and needs this process's model client,
  spending and request policy.
* ``EXULANICA_REFERENCE_WORKSPACES``: a JSON array of the workspace ids that may ask for web notes.
  Absent, none may. A source whose catalog entry is ``operator_only`` is offered to these
  workspaces only, and on an installation whose profile is ``public`` to none at all.
* A source is configured when its credential variable is set and the egress allowlist declares its
  origin; :func:`configured_adapter` builds its adapter, or refuses as
  ``references_not_configured`` naming what is missing and never the credential.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Final

from exulanica.env import env_name
from exulanica.models.egress import EgressError, load_egress_allowlist
from exulanica.references.adapters import (
    ReferenceAdapter,
    ReferenceSourceUnavailable,
    adapter_for,
    source_transport,
)
from exulanica.references.catalogs import ReferenceSource

__all__ = [
    "REFERENCE_WORKER_ENV",
    "REFERENCE_WORKSPACES_ENV",
    "ReferenceSettingRefused",
    "configured_adapter",
    "plays_references_here",
    "reference_workspaces",
]

REFERENCE_WORKER_ENV: Final = env_name("REFERENCE_WORKER")
REFERENCE_WORKSPACES_ENV: Final = env_name("REFERENCE_WORKSPACES")


class ReferenceSettingRefused(ValueError):
    """A reference setting this process will not start with, named by code and variable."""

    def __init__(self, code: str, variable: str) -> None:
        super().__init__(f"{code}: {variable}")
        self.code = code
        self.variable = variable


def plays_references_here(value: str | None) -> bool:
    """Whether this process plays reference jobs (``EXULANICA_REFERENCE_WORKER``)."""
    normalized = (value or "").strip().lower()
    if normalized in ("", "1", "true", "on", "yes", "here"):
        return True
    if normalized in ("0", "false", "off", "no"):
        return False
    raise ReferenceSettingRefused("reference_worker_not_recognised", REFERENCE_WORKER_ENV)


def reference_workspaces(value: str | None) -> tuple[uuid.UUID, ...]:
    """The workspaces that may ask for web notes, or a named refusal of a list half read."""
    if value is None or not value.strip():
        return ()
    try:
        document = json.loads(value)
    except json.JSONDecodeError:
        raise ReferenceSettingRefused(
            "reference_workspaces_not_json", REFERENCE_WORKSPACES_ENV
        ) from None
    if not isinstance(document, list):
        raise ReferenceSettingRefused("reference_workspaces_not_array", REFERENCE_WORKSPACES_ENV)
    workspaces: list[uuid.UUID] = []
    for entry in document:
        try:
            if not isinstance(entry, str):
                raise ValueError(entry)
            workspaces.append(uuid.UUID(entry))
        except ValueError:
            raise ReferenceSettingRefused(
                "reference_workspaces_not_uuid", REFERENCE_WORKSPACES_ENV
            ) from None
    if len(set(workspaces)) != len(workspaces):
        raise ReferenceSettingRefused("reference_workspaces_duplicate", REFERENCE_WORKSPACES_ENV)
    return tuple(workspaces)


def configured_adapter(source: ReferenceSource, environ: Mapping[str, str]) -> ReferenceAdapter:
    """``source``'s adapter over the egress allowlist narrowed to its origin, or a refusal."""
    try:
        transport = source_transport(source, load_egress_allowlist(environ))
    except EgressError as missing:
        raise ReferenceSourceUnavailable(
            "references_not_configured",
            f"the egress allowlist does not declare {source.egress_origin}",
            charged=False,
        ) from missing
    try:
        return adapter_for(source, transport=transport, environ=environ)
    except ReferenceSourceUnavailable:
        transport.close()
        raise
