"""What every reference source adapter shares: the leads it returns, its refusals, its transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

from exulanica.errors import ExulanicaError
from exulanica.models.egress import EgressAllowlist
from exulanica.models.transport import HttpxTransport
from exulanica.references.boundary import AdmittedQuery
from exulanica.references.catalogs import ReferenceSource

__all__ = [
    "SOURCE_REFUSALS",
    "Leads",
    "ReferenceAdapter",
    "ReferenceSourceUnavailable",
    "source_transport",
]

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


class ReferenceAdapter(Protocol):
    """What a source's adapter does: send one admitted query, return its leads."""

    source: ReferenceSource

    def search(self, query: AdmittedQuery) -> Leads: ...

    def close(self) -> None: ...


def source_transport(source: ReferenceSource, egress: EgressAllowlist) -> HttpxTransport:
    """The model transport, held to the deployment's allowlist narrowed to ``source``'s origin."""
    return HttpxTransport(
        egress=egress.narrowed_to(
            [source.egress_origin], purpose=f"the {source.label} reference source"
        )
    )
