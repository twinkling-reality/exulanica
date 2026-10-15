"""Tavily web search, as a leads source.

Sends exactly the request shape the catalog entry states: its search depth (the basic depth costs
one credit), at most its result count, picture descriptions asked for so no picture ever has to be
fetched, no generated answer, no page text beyond Tavily's own excerpts, safe search on, and the
credit usage reported back. The answer is read for its excerpts and picture descriptions; every
address, title, favicon and picture address in it is dropped as it is read.

A picture search (:meth:`TavilySearch.search_pictures`) sends the same request and reads the same
leads, and also keeps the answer's picture addresses that a page may show
(:func:`~exulanica.references.adapters.base.picture_address`), at most
:data:`~exulanica.references.adapters.base.MAX_WEB_PICTURES`, each with its description where
Tavily gave one: what the catalog entry passes, for the person who asked.

The usage Tavily reports is checked against the catalog's cost per call. A different figure means
the shape no longer costs what was admitted, so the call is refused as
``reference_cost_changed`` (already charged) and the source stops until the catalog is reviewed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Final

from exulanica.models.errors import TransportError
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import Transport
from exulanica.references.adapters.base import (
    MAX_WEB_PICTURES,
    Leads,
    PictureLeads,
    ReferenceSourceUnavailable,
    WebPicture,
    picture_address,
    search_timeout_seconds,
)
from exulanica.references.boundary import AdmittedQuery
from exulanica.references.catalogs import ReferenceSource

__all__ = [
    "MAX_ANSWER_CHARACTERS",
    "MAX_PASSAGE_CHARACTERS",
    "MAX_PICTURE_DESCRIPTIONS",
    "TavilySearch",
]

#: An excerpt longer than this is cut: the basic depth returns chunks of at most 500 characters,
#: three per result, as Tavily's search reference (read 2026-10-06) states.
MAX_PASSAGE_CHARACTERS: Final = 1600
MAX_PICTURE_DESCRIPTIONS: Final = 40
#: An answer longer than this is refused unread: five results at the basic depth with picture
#: descriptions are well under 100,000 characters. The shared transport has read it by then, within
#: its deadline; this bounds what the adapter parses and holds.
MAX_ANSWER_CHARACTERS: Final = 1_000_000
MAX_DESCRIPTION_CHARACTERS: Final = 400
_REQUEST_ID: Final = re.compile(r"[A-Za-z0-9-]{1,64}")
_STATUS_REFUSALS: Final = {
    401: "reference_source_refused",
    403: "reference_source_refused",
    429: "reference_source_rate_limited",
    432: "reference_source_plan_limit",
    433: "reference_source_plan_limit",
}


class TavilySearch:
    """One Tavily search per admitted query."""

    key: ClassVar[str] = "tavily_search"

    def __init__(self, source: ReferenceSource, *, transport: Transport, credential: str) -> None:
        if source.key != self.key:
            raise ValueError(f"the Tavily adapter serves {self.key}, not {source.key}")
        if not credential:
            raise ValueError("the Tavily adapter needs a credential")
        self.source = source
        self._transport = transport
        self._credential = credential

    def close(self) -> None:
        """Release the transport's connections; the adapter sends nothing after."""
        close = getattr(self._transport, "close", None)
        if callable(close):
            close()

    def payload(self, query: AdmittedQuery) -> dict[str, Any]:
        """The request body for ``query``: the catalog's shape and nothing else."""
        return {
            "query": query.text,
            "search_depth": self.source.search_depth,
            "max_results": self.source.max_results,
            "include_images": True,
            "include_image_descriptions": True,
            "include_answer": False,
            "include_raw_content": False,
            "include_favicon": False,
            "include_usage": True,
            "safe_search": True,
        }

    def search(self, query: AdmittedQuery) -> Leads:
        return self._leads(query, self._answer(query))

    def search_pictures(self, query: AdmittedQuery) -> PictureLeads:
        """One search, its leads and the pictures it found that a page may show."""
        if not {"image_address", "image_description"} <= set(self.source.passed):
            raise TypeError("this source's catalog entry passes no pictures")
        body = self._answer(query)
        leads = self._leads(query, body)
        return PictureLeads(leads=leads, pictures=_pictures(body))

    def _answer(self, query: AdmittedQuery) -> Mapping[str, Any]:
        """Tavily's answer to ``query``, read as JSON, or why there is none."""
        if not isinstance(query, AdmittedQuery) or query.source != self.source.key:
            raise TypeError("the Tavily adapter sends only a query admitted for it")
        try:
            response = self._transport.post_json(
                self.source.endpoint,
                headers={
                    "Authorization": f"Bearer {self._credential}",
                    "Content-Type": "application/json",
                },
                payload=self.payload(query),
                timeout=search_timeout_seconds(load_manifest().timeout_rule),
            )
        except TransportError as failure:
            raise ReferenceSourceUnavailable(
                "reference_source_down",
                "no whole answer from Tavily",
                charged=failure.reached_provider is not False,
            ) from failure
        if not response.ok:
            # The body is never quoted: an error page is not ours to keep either.
            raise ReferenceSourceUnavailable(
                _STATUS_REFUSALS.get(response.status_code, "reference_source_down"),
                f"Tavily answered HTTP {response.status_code}",
                charged=response.status_code >= 500,
            )
        if len(response.text) > MAX_ANSWER_CHARACTERS:
            raise ReferenceSourceUnavailable(
                "reference_answer_unreadable", "Tavily's answer is larger than read", charged=True
            )
        try:
            body = response.json_body()
        except TransportError as failure:
            raise ReferenceSourceUnavailable(
                "reference_answer_unreadable", "Tavily's answer is not JSON", charged=True
            ) from failure
        if not isinstance(body, Mapping):
            raise _unreadable("the answer is not an object")
        return body

    def _leads(self, query: AdmittedQuery, body: Mapping[str, Any]) -> Leads:
        usage = body.get("usage")
        credits = usage.get("credits") if isinstance(usage, Mapping) else None
        if type(credits) is not int:
            raise _unreadable("the answer reports no credit usage")
        if credits != self.source.cost_per_call:
            raise ReferenceSourceUnavailable(
                "reference_cost_changed",
                f"the call cost {credits} credits where the catalog admits "
                f"{self.source.cost_per_call}",
                charged=True,
                credits=credits,
            )
        results = body.get("results")
        if not isinstance(results, Sequence) or isinstance(results, str | bytes):
            raise _unreadable("the answer has no result list")
        results = list(results)[: self.source.max_results]
        passages: list[str] = []
        descriptions: list[str] = []
        _descriptions(body.get("images"), descriptions)
        for result in results:
            if not isinstance(result, Mapping):
                raise _unreadable("a result is not an object")
            content = result.get("content")
            if isinstance(content, str) and content.strip():
                passages.append(content.strip()[:MAX_PASSAGE_CHARACTERS])
            _descriptions(result.get("images"), descriptions)
        request_id = body.get("request_id")
        return Leads(
            query=query,
            passages=tuple(passages),
            picture_descriptions=tuple(dict.fromkeys(descriptions))[:MAX_PICTURE_DESCRIPTIONS],
            result_count=len(results),
            credits=credits,
            request_id=(
                request_id
                if isinstance(request_id, str) and _REQUEST_ID.fullmatch(request_id)
                else None
            ),
        )


def _descriptions(images: object, into: list[str]) -> None:
    """The text descriptions among ``images``; a bare address or an address field is dropped."""
    if not isinstance(images, Sequence) or isinstance(images, str | bytes):
        return
    for image in images:
        if isinstance(image, Mapping):
            description = image.get("description")
            if isinstance(description, str) and description.strip():
                into.append(description.strip()[:MAX_DESCRIPTION_CHARACTERS])


def _pictures(body: Mapping[str, Any]) -> tuple[WebPicture, ...]:
    """The answer's pictures a page may show, first the answer's own then each result's, each
    address once, at most :data:`MAX_WEB_PICTURES`; a picture with no description keeps none."""
    found: dict[str, WebPicture] = {}
    results = body.get("results")
    lists = [body.get("images")] + (
        [result.get("images") for result in results if isinstance(result, Mapping)]
        if isinstance(results, Sequence) and not isinstance(results, str | bytes)
        else []
    )
    for images in lists:
        if not isinstance(images, Sequence) or isinstance(images, str | bytes):
            continue
        for image in images:
            address = image.get("url") if isinstance(image, Mapping) else image
            shown = picture_address(address)
            if shown is None or shown[0] in found:
                continue
            description = image.get("description") if isinstance(image, Mapping) else None
            found[shown[0]] = WebPicture(
                address=shown[0],
                website=shown[1],
                description=(
                    description.strip()[:MAX_DESCRIPTION_CHARACTERS]
                    if isinstance(description, str) and description.strip()
                    else None
                ),
            )
            if len(found) == MAX_WEB_PICTURES:
                return tuple(found.values())
    return tuple(found.values())


def _unreadable(detail: str) -> ReferenceSourceUnavailable:
    return ReferenceSourceUnavailable("reference_answer_unreadable", detail, charged=True)
