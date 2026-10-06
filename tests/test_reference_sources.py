"""The reference-source catalog, its adapter per source, and what the Tavily adapter sends.

Expected values are written from Tavily's search reference and terms as read on 2026-10-06
(deliveries recorded in THIRD_PARTY_NOTICES.md section 3.4), not computed by the code under test.
No test reaches a network: the adapter is driven through the scripted transport.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.models.egress import EgressConfigurationError, EgressRefused, parse_egress_allowlist
from exulanica.models.errors import TransportError
from exulanica.models.transport import HttpResponse
from exulanica.references import catalogs as catalogs_module
from exulanica.references.adapters import (
    ADAPTERS,
    ReferenceSourceUnavailable,
    adapter_for,
    source_transport,
)
from exulanica.references.adapters.tavily import TavilySearch
from exulanica.references.boundary import AdmittedQuery, SearchSubject, admit_query
from exulanica.references.catalogs import CATALOG_DIRECTORY, load_reference_catalogs

from model_fakes import FakeTransport

PLANTED_ADDRESS = "https://planted-result.example/page-4471"
PLANTED_PICTURE = "https://planted-images.example/photo-9917.jpg"
PLANTED_TITLE = "Planted Title Wrenfield Almanac"
CREDENTIAL = "tvly-planted-credential-5521"


class _Admits:
    def admit(self, request):
        return request.texts


def _source():
    return load_reference_catalogs().sources["tavily_search"]


def _query(text: str = "whitewashed island houses", aspect: str = "buildings") -> AdmittedQuery:
    return admit_query(SearchSubject(text, aspect), source=_source(), policy=_Admits())


def _answer(*, credits: object = 1) -> HttpResponse:
    body = {
        "query": "whitewashed island houses",
        "results": [
            {
                "title": PLANTED_TITLE,
                "url": PLANTED_ADDRESS,
                "content": "Cube-shaped houses with flat roofs and blue doors line the lanes.",
                "score": 0.8,
                "favicon": "https://planted-result.example/favicon.png",
                "images": [
                    {"url": PLANTED_PICTURE, "description": "A blue dome above white walls"}
                ],
            },
            {
                "title": "Second",
                "url": "https://planted-result.example/2",
                "content": "Stone quays.",
            },
        ],
        "images": [
            PLANTED_PICTURE,
            {"url": PLANTED_PICTURE, "description": "Stepped lanes between white houses"},
        ],
        "response_time": "1.2",
        "usage": {"credits": credits},
        "request_id": "123e4567-e89b-12d3-a456-426614174111",
    }
    return HttpResponse(status_code=200, text=json.dumps(body))


def test_every_catalogued_source_has_exactly_one_adapter_and_every_adapter_a_source() -> None:
    catalogued = set(load_reference_catalogs().sources)
    assert catalogued == {"tavily_search"}
    assert set(ADAPTERS) == catalogued


def test_the_tavily_entry_states_what_the_terms_read_allow() -> None:
    source = _source()
    assert source.kind == "leads"
    assert source.endpoint == "https://api.tavily.com/search"
    assert source.credential_env == "TAVILY_API_KEY"
    assert (source.terms_updated, source.terms_read) == ("2026-05-04", "2026-10-06")
    assert source.kept == ("query", "request_record")
    assert source.shown == ("request_record",)
    assert source.exported == ()
    assert source.availability == "operator_only"
    assert (source.cost_unit, source.cost_per_call, source.search_depth) == ("credit", 1, "basic")


def _tampered(tmp_path: Path, change) -> Path:
    directory = tmp_path / "reference-sources"
    shutil.copytree(CATALOG_DIRECTORY, directory)
    path = directory / "reference-source.v1.json"
    document = json.loads(path.read_text())
    change(document["entries"][0])
    path.write_text(json.dumps(document))
    return directory


TAMPERED = {
    "a leads source keeping result text": lambda e: e.update(
        kept=["query", "request_record", "result_text"]
    ),
    "shown without being kept": lambda e: e.update(
        shown=["request_record", "query"], kept=["request_record"]
    ),
    "a records source before its admission exists": lambda e: e.update(kind="records"),
    "a plain http origin": lambda e: e.update(egress_origin="http://api.tavily.com"),
    "an origin with a path": lambda e: e.update(egress_origin="https://api.tavily.com/search"),
    "a fractional cost": lambda e: e.update(cost_per_call=1.0),
    "the advanced depth's shape is not offered": lambda e: e.update(search_depth="advanced"),
    "an unknown data class": lambda e: e.update(kept=["query", "everything"]),
    "a missing field": lambda e: e.pop("availability"),
}


@pytest.mark.parametrize("case", sorted(TAMPERED))
def test_a_tampered_source_catalog_is_refused(tmp_path: Path, case: str) -> None:
    load_reference_catalogs(CATALOG_DIRECTORY)  # positive control: the shipped file reads
    directory = _tampered(tmp_path, TAMPERED[case])
    with pytest.raises(CatalogError):
        catalogs_module.load_reference_catalogs(directory)


def test_the_adapter_sends_the_catalogued_shape_and_nothing_else() -> None:
    transport = FakeTransport([_answer()])
    adapter = adapter_for(_source(), transport=transport, environ={"TAVILY_API_KEY": CREDENTIAL})
    adapter.search(_query())
    (request,) = transport.requests
    assert request["url"] == "https://api.tavily.com/search"
    assert request["headers"]["Authorization"] == f"Bearer {CREDENTIAL}"
    assert request["payload"] == {
        "query": "whitewashed island houses",
        "search_depth": "basic",
        "max_results": 5,
        "include_images": True,
        "include_image_descriptions": True,
        "include_answer": False,
        "include_raw_content": False,
        "include_favicon": False,
        "include_usage": True,
        "safe_search": True,
    }


def test_leads_hold_excerpts_and_picture_descriptions_and_no_address_title_or_picture() -> None:
    transport = FakeTransport([_answer()])
    leads = TavilySearch(_source(), transport=transport, credential=CREDENTIAL).search(_query())
    assert leads.passages == (
        "Cube-shaped houses with flat roofs and blue doors line the lanes.",
        "Stone quays.",
    )
    assert leads.picture_descriptions == (
        "Stepped lanes between white houses",
        "A blue dome above white walls",
    )
    assert (leads.result_count, leads.credits) == (2, 1)
    assert leads.request_id == "123e4567-e89b-12d3-a456-426614174111"
    everything = json.dumps(
        {f.name: str(getattr(leads, f.name)) for f in dataclasses.fields(leads)}
    ) + repr(leads)
    for planted in (
        PLANTED_ADDRESS,
        PLANTED_PICTURE,
        PLANTED_TITLE,
        "planted-result.example",
        CREDENTIAL,
    ):
        assert planted not in everything
    # A lead's words never reach a log line by way of its repr.
    assert "Cube-shaped" not in repr(leads)


def test_a_call_that_costs_other_than_the_catalog_admits_stops_the_source() -> None:
    adapter = TavilySearch(
        _source(), transport=FakeTransport([_answer(credits=2)]), credential=CREDENTIAL
    )
    with pytest.raises(ReferenceSourceUnavailable) as refused:
        adapter.search(_query())
    assert (refused.value.code, refused.value.charged) == ("reference_cost_changed", True)


@pytest.mark.parametrize("credits", [None, "1", 1.0, True])
def test_an_answer_without_a_whole_credit_count_is_unreadable(credits: object) -> None:
    adapter = TavilySearch(
        _source(), transport=FakeTransport([_answer(credits=credits)]), credential=CREDENTIAL
    )
    with pytest.raises(ReferenceSourceUnavailable) as refused:
        adapter.search(_query())
    assert refused.value.code == "reference_answer_unreadable"


@pytest.mark.parametrize(
    ("status", "code", "charged"),
    [
        (401, "reference_source_refused", False),
        (403, "reference_source_refused", False),
        (429, "reference_source_rate_limited", False),
        (432, "reference_source_plan_limit", False),
        (433, "reference_source_plan_limit", False),
        (500, "reference_source_down", True),
        (400, "reference_source_down", False),
    ],
)
def test_a_refusal_is_named_and_never_quotes_the_body(
    status: int, code: str, charged: bool
) -> None:
    error = HttpResponse(status_code=status, text=json.dumps({"detail": PLANTED_TITLE}))
    adapter = TavilySearch(_source(), transport=FakeTransport([error]), credential=CREDENTIAL)
    with pytest.raises(ReferenceSourceUnavailable) as refused:
        adapter.search(_query())
    assert (refused.value.code, refused.value.charged) == (code, charged)
    assert PLANTED_TITLE not in str(refused.value)


def test_a_connection_never_made_is_not_charged() -> None:
    failure = TransportError("no connection", reached_provider=False)
    adapter = TavilySearch(_source(), transport=FakeTransport([failure]), credential=CREDENTIAL)
    with pytest.raises(ReferenceSourceUnavailable) as refused:
        adapter.search(_query())
    assert (refused.value.code, refused.value.charged) == ("reference_source_down", False)


def test_without_its_credential_a_source_is_not_offered() -> None:
    with pytest.raises(ReferenceSourceUnavailable) as refused:
        adapter_for(_source(), transport=FakeTransport(), environ={"TAVILY_API_KEY": "  "})
    assert refused.value.code == "references_not_configured"


def test_the_adapter_sends_only_a_query_admitted_for_it() -> None:
    transport = FakeTransport([_answer()])
    adapter = TavilySearch(_source(), transport=transport, credential=CREDENTIAL)
    with pytest.raises(TypeError):
        adapter.search("whitewashed island houses")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        AdmittedQuery(source="tavily_search", text="anything", aspect="buildings", seal=object())
    other = dataclasses.replace(_query(), source="another_source")
    with pytest.raises(TypeError):
        adapter.search(other)
    assert transport.requests == []


def test_the_transport_reaches_the_source_origin_and_no_other() -> None:
    shared = parse_egress_allowlist(
        ["https://api.tokenfactory.nebius.com", "https://api.tavily.com"]
    )
    transport = source_transport(_source(), shared)
    assert {str(origin) for origin in transport.egress.origins} == {"https://api.tavily.com"}
    with pytest.raises(EgressRefused):
        transport.post_json(
            "https://api.tokenfactory.nebius.com/v1/chat/completions",
            headers={},
            payload={},
            timeout=1.0,
        )
    transport.close()
    with pytest.raises(EgressConfigurationError):
        source_transport(_source(), parse_egress_allowlist(["https://api.tokenfactory.nebius.com"]))


def test_no_request_id_that_is_not_one_is_kept() -> None:
    body = json.loads(_answer().text)
    body["request_id"] = PLANTED_ADDRESS
    adapter = TavilySearch(
        _source(),
        transport=FakeTransport([HttpResponse(200, json.dumps(body))]),
        credential=CREDENTIAL,
    )
    assert adapter.search(_query()).request_id is None
