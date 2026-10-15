"""What every reference source adapter shares: the leads it returns, its refusals, its transport.

A picture search also returns :class:`PictureLeads`: the leads, and the web pictures it found,
each an address its source passes (``passed`` in its catalog entry) and nothing more. The pictures
are held apart from :class:`Leads`, so a lead still holds no address of any kind.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Final, Protocol
from urllib.parse import urlsplit

from exulanica.errors import ExulanicaError
from exulanica.models.egress import EgressAllowlist
from exulanica.models.manifest import TimeoutRule
from exulanica.models.transport import HttpxTransport
from exulanica.references.boundary import AdmittedQuery
from exulanica.references.catalogs import ReferenceSource

__all__ = [
    "MAX_PICTURE_ADDRESS_CHARACTERS",
    "MAX_WEB_PICTURES",
    "SEARCH_LONGEST_MS",
    "SOURCE_REFUSALS",
    "Leads",
    "PictureLeads",
    "ReferenceAdapter",
    "ReferenceSourceUnavailable",
    "WebPicture",
    "picture_address",
    "search_timeout_seconds",
    "source_transport",
]

#: The most pictures one picture search passes on: a page shows them at once.
MAX_WEB_PICTURES: Final = 8
#: A longer picture address is left out rather than cut.
MAX_PICTURE_ADDRESS_CHARACTERS: Final = 2048
_ADDRESS_CHARACTERS: Final = re.compile(r"[!-~]+")
_NUMERIC_HOST: Final = re.compile(r"[0-9.]+|0x[0-9a-f.x]*", re.IGNORECASE)

#: The longest dispatch-to-settle latency among the eighteen Tavily searches in the two
#: LOOKUP live checks on 2026-10-09 (main 7eef51d1 and 49d0d00b). Both the transport and the
#: worker's search stage apply the manifest's timeout rule to this same measured basis.
SEARCH_LONGEST_MS: Final = 17440


def search_timeout_seconds(rule: TimeoutRule) -> float:
    """The search transport and stage allowance, derived from the measured search latency."""
    return float(rule.timeout_for(SEARCH_LONGEST_MS))


#: Why a source answered nothing usable, by code, as the capability descriptors will name it.
SOURCE_REFUSALS: Final = (
    "references_not_configured",
    "reference_source_down",
    "reference_source_refused",
    "reference_source_rate_limited",
    "reference_source_plan_limit",
    "reference_cost_changed",
    "reference_answer_unreadable",
)


class ReferenceSourceUnavailable(ExulanicaError):
    """A source answered nothing usable. ``code`` is one of :data:`SOURCE_REFUSALS`.

    ``charged`` says whether the source may have counted the call against its allowance: a request
    that reached it and was answered, however badly, may have been; ``credits`` is what the source
    said the call cost, where it said.
    """

    def __init__(
        self, code: str, detail: str, *, charged: bool, credits: int | None = None
    ) -> None:
        if code not in SOURCE_REFUSALS:
            raise ValueError(f"unknown source refusal {code!r}")
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.charged = charged
        #: The credits the source reported for the call, where it reported any.
        self.credits = credits


@dataclass(frozen=True, slots=True)
class Leads:
    """What one search returned that a reader may draft from, and the facts of the exchange.

    ``passages`` and ``picture_descriptions`` are the source's words: held in memory for the job
    that asked and never written anywhere. ``result_count``, ``credits`` and ``request_id`` are our
    record of the call and may be kept.
    """

    query: AdmittedQuery
    passages: tuple[str, ...]
    picture_descriptions: tuple[str, ...]
    result_count: int
    credits: int
    request_id: str | None

    def __repr__(self) -> str:
        # A lead's words never reach a log line by way of a repr.
        return (
            f"Leads(source={self.query.source!r}, passages={len(self.passages)}, "
            f"picture_descriptions={len(self.picture_descriptions)}, "
            f"result_count={self.result_count}, credits={self.credits})"
        )


@dataclass(frozen=True, slots=True)
class WebPicture:
    """A picture a search found: its address, the website it is on and its words, if any.

    Passed to the person who asked and held in this process's memory for their request only
    (:mod:`exulanica.references.held_pictures`); never written to a database, a store or a log.
    """

    address: str
    website: str
    description: str | None

    def __repr__(self) -> str:
        # An address never reaches a log line by way of a repr.
        return f"WebPicture(described={self.description is not None})"


@dataclass(frozen=True, slots=True)
class PictureLeads:
    """What one picture search returned: its leads, and the pictures it found, in its order."""

    leads: Leads
    pictures: tuple[WebPicture, ...]

    def __repr__(self) -> str:
        return f"PictureLeads({self.leads!r}, pictures={len(self.pictures)})"


def picture_address(value: object) -> tuple[str, str] | None:
    """``value`` and its website when it is a picture address a page may show, or None.

    Only an ``https`` address of at most :data:`MAX_PICTURE_ADDRESS_CHARACTERS` printable ASCII
    characters, naming a host (never an address, a numeric shorthand for one or a name ending in a
    dot) on the default port, with no user or password in it.
    """
    if not isinstance(value, str) or len(value) > MAX_PICTURE_ADDRESS_CHARACTERS:
        return None
    if _ADDRESS_CHARACTERS.fullmatch(value) is None or "\\" in value:
        return None
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        return None
    host = parts.hostname
    if parts.scheme != "https" or not host or "@" in parts.netloc or port not in (None, 443):
        return None
    if host.endswith(".") or "." not in host or _NUMERIC_HOST.fullmatch(host) is not None:
        return None
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return value, host.lower()
    return None


class ReferenceAdapter(Protocol):
    """What a source's adapter does: send one admitted query, return its leads; or, for a source
    that passes pictures, its leads and the pictures it found."""

    source: ReferenceSource

    def search(self, query: AdmittedQuery) -> Leads: ...

    def search_pictures(self, query: AdmittedQuery) -> PictureLeads: ...

    def close(self) -> None: ...


def source_transport(source: ReferenceSource, egress: EgressAllowlist) -> HttpxTransport:
    """The model transport, held to the deployment's allowlist narrowed to ``source``'s origin."""
    return HttpxTransport(
        egress=egress.narrowed_to(
            [source.egress_origin], purpose=f"the {source.label} reference source"
        )
    )
