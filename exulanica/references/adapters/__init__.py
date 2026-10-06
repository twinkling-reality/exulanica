"""One adapter per reference source, keyed as the source catalog keys it.

An adapter sends an :class:`~exulanica.references.boundary.AdmittedQuery` and nothing else, in the
one request shape its catalog entry states, to the one origin it states, through the model
transport held to the egress allowlist narrowed to that origin. It returns :class:`Leads`: the
words a reader may draft notes from, and the facts of the exchange we record. A lead holds no
address, title or picture of any kind, and lives only as long as the job that asked for it.

``ADAPTERS`` and the source catalog name the same sources; ``tests/test_reference_sources.py``
holds them to it.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from exulanica.models.transport import Transport
from exulanica.references.adapters.base import (
    SOURCE_REFUSALS,
    Leads,
    ReferenceAdapter,
    ReferenceSourceUnavailable,
    source_transport,
)
from exulanica.references.adapters.tavily import TavilySearch
from exulanica.references.catalogs import ReferenceSource

__all__ = [
    "ADAPTERS",
    "SOURCE_REFUSALS",
    "Leads",
    "ReferenceAdapter",
    "ReferenceSourceUnavailable",
    "adapter_for",
    "source_transport",
]

#: Every adapter by the source key it serves.
ADAPTERS: Final[Mapping[str, type[TavilySearch]]] = MappingProxyType(
    {TavilySearch.key: TavilySearch}
)


def adapter_for(
    source: ReferenceSource, *, transport: Transport, environ: Mapping[str, str]
) -> ReferenceAdapter:
    """``source``'s adapter, with its credential read from ``environ``."""
    if source.key not in ADAPTERS:
        raise ReferenceSourceUnavailable(
            "references_not_configured", f"no adapter serves {source.key}", charged=False
        )
    credential = environ.get(source.credential_env, "").strip()
    if not credential:
        raise ReferenceSourceUnavailable(
            "references_not_configured",
            f"{source.credential_env} is not set, so {source.label} is not offered",
            charged=False,
        )
    return ADAPTERS[source.key](source, transport=transport, credential=credential)
