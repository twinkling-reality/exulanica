"""A picture search: the person's words as the one search, the pictures it finds passed to them
from this process's memory, and nothing of a picture written anywhere.

On recorded answers only: Tavily answers through the real adapter over a scripted transport, so no
search is sent and nothing is spent. The pictures' addresses are planted, and none may be found in
a row the work wrote, a bundle or a lead.
"""

from __future__ import annotations

import dataclasses
import json
import uuid

import pytest
from exulanica.models.transport import HttpResponse
from exulanica.references import drafting, store
from exulanica.references.adapters.base import (
    MAX_WEB_PICTURES,
    WebPicture,
    picture_address,
)
from exulanica.references.adapters.tavily import TavilySearch
from exulanica.references.boundary import AdmittedQuery, SearchSubject, admit_query
from exulanica.references.catalogs import load_reference_catalogs
from exulanica.references.held_pictures import PictureHolding, held_pictures
from exulanica.references.settings import ReferenceSettingRefused, searches_web_pictures_here
from psycopg.rows import tuple_row

from model_fakes import FakeTransport
from test_reference_routes import OTHER_ACTOR_TOKEN, STRANGER_TOKEN, TOKEN
from test_reference_routes import _bench_alias as _bench_alias
from test_reference_routes import _named_alias as _named_alias
from test_reference_routes import api as api
from test_reference_routes import saved_named as saved_named
from test_reference_routes import spending_bench as spending_bench
from test_reference_worker import scene as scene

DUCK = "https://pictures.example/yellow-duck-holding-its-head.jpg"
POND = "https://ponds.example/a/b/pond.png?size=large"
CREDENTIAL = "tvly-planted-credential-6630"
WORDS = "yellow duck holding its head"


class _Admits:
    def admit(self, request):
        return request.texts


def _source(version: int = 2):
    return load_reference_catalogs(source_version=version).sources["tavily_search"]


def _query(source=None) -> AdmittedQuery:
    source = source or _source()
    return admit_query(
        SearchSubject(WORDS, "anatomy"),
        source=source,
        policy=_Admits(),
        catalogs=load_reference_catalogs(aspect_version=2),
    )


def _answer(images: list, results: list | None = None) -> HttpResponse:
    return HttpResponse(
        200,
        json.dumps(
            {
                "query": WORDS,
                "results": results
                if results is not None
                else [
                    {"title": "A pond page", "url": "https://ponds.example/", "content": "Ducks."}
                ],
                "images": images,
                "usage": {"credits": 1},
                "request_id": "123e4567-e89b-12d3-a456-426614174222",
            }
        ),
    )


@pytest.mark.parametrize(
    ("address", "website"),
    [
        (DUCK, "pictures.example"),
        ("https://CDN.Pictures.example:443/x.webp", "cdn.pictures.example"),
        ("http://pictures.example/a.jpg", None),
        ("https://192.168.1.4/a.jpg", None),
        ("https://[::1]/a.jpg", None),
        ("https://127.1/a.jpg", None),
        ("https://0x7f000001/a.jpg", None),
        ("https://localhost/a.jpg", None),
        ("https://pictures.example./a.jpg", None),
        ("https://someone:secret@pictures.example/a.jpg", None),
        ("https://pictures.example:8443/a.jpg", None),
        ("https://pictures.example/a b.jpg", None),
        ("https://pictures.example/\\a.jpg", None),
        ("https://bilder.example/ä.jpg", None),
        ("https://pictures.example/" + "a" * 2048, None),
        (None, None),
        ({"url": DUCK}, None),
    ],
)
def test_only_an_https_address_naming_a_host_may_be_shown(address, website) -> None:
    shown = picture_address(address)
    assert (shown[1] if shown else None) == website
    if shown:
        assert shown[0] == address


def test_a_picture_search_passes_the_pictures_a_page_may_show_and_its_leads_hold_none() -> None:
    transport = FakeTransport(
        [
            _answer(
                [
                    {"url": DUCK, "description": "  A yellow duck holds its head  "},
                    "http://pictures.example/plain.jpg",
                    {"url": "https://10.0.0.8/inside.jpg", "description": "Inside"},
                    POND,
                    {"url": DUCK, "description": "The same picture again"},
                ],
                results=[
                    {
                        "url": "https://ponds.example/",
                        "content": "Ducks rest by the pond.",
                        "images": [{"url": "https://reeds.example/r.jpg", "description": ""}],
                    }
                ],
            )
        ]
    )
    found = TavilySearch(_source(), transport=transport, credential=CREDENTIAL).search_pictures(
        _query()
    )
    assert found.pictures == (
        WebPicture(DUCK, "pictures.example", "A yellow duck holds its head"),
        WebPicture(POND, "ponds.example", None),
        WebPicture("https://reeds.example/r.jpg", "reeds.example", None),
    )
    # The same request as any search, and the same leads: words only.
    assert transport.requests[0]["payload"]["include_images"] is True
    assert found.leads.passages == ("Ducks rest by the pond.",)
    lead = repr(found.leads) + json.dumps(
        {
            field.name: str(getattr(found.leads, field.name))
            for field in dataclasses.fields(found.leads)
        }
    )
    for planted in (DUCK, POND, "pictures.example", CREDENTIAL):
        assert planted not in lead
        assert planted not in repr(found)


def test_a_picture_search_passes_at_most_eight_pictures() -> None:
    many = [
        {"url": f"https://pictures.example/{n}.jpg", "description": f"Duck {n}"} for n in range(12)
    ]
    found = TavilySearch(
        _source(), transport=FakeTransport([_answer(many)]), credential=CREDENTIAL
    ).search_pictures(_query())
    assert [picture.address for picture in found.pictures] == [
        f"https://pictures.example/{n}.jpg" for n in range(MAX_WEB_PICTURES)
    ]


def test_a_source_whose_catalog_passes_no_pictures_is_never_asked_for_them() -> None:
    first = _source(version=1)
    transport = FakeTransport([_answer([DUCK])])
    with pytest.raises(TypeError, match="passes no pictures"):
        TavilySearch(first, transport=transport, credential=CREDENTIAL).search_pictures(
            _query(first)
        )
    assert transport.requests == []


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _pictures(count: int = 2) -> tuple[WebPicture, ...]:
    return tuple(
        WebPicture(f"https://pictures.example/{n}.jpg", "pictures.example", None)
        for n in range(count)
    )


def test_held_pictures_are_read_until_their_time_is_up_and_then_gone() -> None:
    clock = _Clock()
    holding = PictureHolding(clock=clock, seconds=1800)
    workspace, reference = uuid.uuid4(), uuid.uuid4()
    holding.hold(workspace, reference, _pictures())
    clock.now += 1799.4
    held = holding.read(workspace, reference)
    assert held is not None and held.pictures == _pictures() and held.seconds_left == 0
    # Another workspace, or another request, reads nothing of them.
    assert holding.read(uuid.uuid4(), reference) is None
    assert holding.read(workspace, uuid.uuid4()) is None
    clock.now += 0.6
    assert holding.read(workspace, reference) is None
    assert len(holding) == 0


def test_a_holding_lets_the_oldest_go_past_its_capacity_and_forgets_on_asking() -> None:
    clock = _Clock()
    holding = PictureHolding(clock=clock, capacity=2)
    workspace = uuid.uuid4()
    first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for reference in (first, second, third):
        holding.hold(workspace, reference, _pictures(1))
    assert holding.read(workspace, first) is None
    assert holding.read(workspace, third) is not None
    holding.forget(workspace, third)
    assert holding.read(workspace, third) is None
    assert len(holding) == 1


def test_a_holding_holds_at_most_eight_pictures_and_shows_no_address_in_a_repr() -> None:
    holding = PictureHolding()
    workspace, reference = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(ValueError):
        holding.hold(workspace, reference, _pictures(MAX_WEB_PICTURES + 1))
    holding.hold(workspace, reference, _pictures(MAX_WEB_PICTURES))
    held = holding.read(workspace, reference)
    assert "pictures.example" not in repr(held)
    assert "pictures.example" not in repr(held.pictures)


@pytest.mark.postgres
def test_a_picture_search_sends_the_persons_words_and_holds_what_it_found(scene) -> None:
    from test_reference_worker import _every_row_as_text, _structured

    connection, workspace_id, models, tavily, gate, worker, _request = scene
    made, _ = store.create_request(
        connection,
        workspace_id,
        offered_to=(workspace_id,),
        owner_actor_id=uuid.uuid4(),
        purpose="things",
        web=True,
        description=WORDS,
        withheld_words=[],
        prompts_sha256=drafting.prompts_for_request("things").sha256,
        web_pictures=True,
    )
    # No planner: the reader is the only model asked.
    models.responses = [
        _structured({"notes": [{"aspect": "anatomy", "text": "broad bill on a rounded head"}]})
    ]
    tavily.responses = [_answer([{"url": DUCK, "description": "A yellow duck"}, POND])]
    holding = PictureHolding()

    assert worker(holding=holding).run_once(workspace_id) == "complete"

    assert [request["payload"]["query"] for request in tavily.requests] == [WORDS]
    assert len(models.requests) == 1
    held = holding.read(workspace_id, made.reference_id)
    assert [picture.address for picture in held.pictures] == [DUCK, POND]
    finished = store.read_request(connection, workspace_id, made.reference_id)
    steps = {step["step"]: step for step in finished.steps}
    assert steps["plan"]["state"] == "skipped"
    assert (steps["search"]["state"], steps["search"]["pictures"]) == ("done", 2)
    assert finished.status == "complete"
    written = _every_row_as_text(connection) + json.dumps(finished.bundle)
    for planted in (DUCK, POND, "pictures.example", "ponds.example"):
        assert planted not in written
    assert len(gate.admitted) == 1


@pytest.mark.postgres
def test_a_picture_search_refused_at_the_boundary_holds_nothing(scene) -> None:
    connection, workspace_id, models, tavily, _gate, worker, _request = scene
    made, _ = store.create_request(
        connection,
        workspace_id,
        offered_to=(workspace_id,),
        owner_actor_id=uuid.uuid4(),
        purpose="things",
        web=True,
        description="duck at www.pictures.example",
        withheld_words=[],
        prompts_sha256=drafting.prompts_for_request("things").sha256,
        web_pictures=True,
    )
    holding = PictureHolding()
    assert worker(holding=holding).run_once(workspace_id) == "partial"
    assert tavily.requests == [] and models.requests == []
    assert holding.read(workspace_id, made.reference_id) is None


def test_a_picture_search_is_a_web_search() -> None:
    with pytest.raises(ValueError, match="web search"):
        store.create_request(
            None,  # type: ignore[arg-type]
            uuid.UUID(int=1),
            offered_to=(uuid.UUID(int=1),),
            owner_actor_id=uuid.UUID(int=2),
            purpose="things",
            web=False,
            description=WORDS,
            withheld_words=[],
            prompts_sha256="0" * 64,
            web_pictures=True,
        )


def _client(api, **changes):
    client, repository = api
    return client(reference_web_pictures=True, **changes), repository


def _ask(client, token=TOKEN, **body):
    payload = {"purpose": "things", "description": WORDS, "web": True, "web_pictures": True, **body}
    return client.post(
        "/worlds/references", json=payload, headers={"Authorization": f"Bearer {token}"}
    )


def _read(client, path, token=TOKEN):
    return client.get(path, headers={"Authorization": f"Bearer {token}"})


@pytest.mark.postgres
def test_a_picture_search_is_queued_and_its_pictures_read_by_its_requester_alone(api) -> None:
    client, repository = _client(api)
    listed = _read(client, "/worlds/references").json()
    assert listed["web_pictures"] == {"offered": True, "code": None, "words": 8}
    answered = _ask(client)
    assert answered.status_code == 202
    reference_id = uuid.UUID(answered.json()["reference_id"])
    payload = (
        repository.connection.cursor(row_factory=tuple_row)
        .execute(
            "select j.payload from job j join reference_request r on r.job_id = j.job_id "
            "where r.reference_id = %s",
            (reference_id,),
        )
        .fetchone()[0]
    )
    assert payload["web_pictures"] is True and payload["description"] == WORDS
    path = f"/worlds/references/{reference_id}/pictures"
    # Nothing is held until the job holds it.
    missing = _read(client, path)
    assert (missing.status_code, missing.json()["code"]) == (404, "pictures_not_held")
    assert missing.headers["cache-control"] == "no-store"
    held_pictures().hold(
        repository.workspace_id,
        reference_id,
        (
            WebPicture(DUCK, "pictures.example", "A yellow duck"),
            WebPicture(POND, "ponds.example", None),
        ),
    )
    try:
        served = _read(client, path)
        assert served.status_code == 200 and served.headers["cache-control"] == "no-store"
        body = served.json()
        assert body["pictures"] == [
            {
                "n": 0,
                "address": DUCK,
                "website": "pictures.example",
                "description": "A yellow duck",
            },
            {"n": 1, "address": POND, "website": "ponds.example", "description": None},
        ]
        assert 0 < body["seconds_left"] <= 1800
        for token in (OTHER_ACTOR_TOKEN, STRANGER_TOKEN):
            elsewhere = _read(client, path, token=token)
            assert (elsewhere.status_code, elsewhere.json()["code"]) == (404, "unknown_reference")
            assert DUCK not in elsewhere.text
        # Stopping the search lets its pictures go.
        stopped = client.post(
            f"/worlds/references/{reference_id}/cancel",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert stopped.json()["status"] == "cancelled"
        assert _read(client, path).json()["code"] == "pictures_not_held"
    finally:
        held_pictures().forget(repository.workspace_id, reference_id)


@pytest.mark.postgres
@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"web": False}, 422, "web_pictures_need_web"),
        ({"purpose": "kind"}, 422, "web_pictures_for_things"),
        (
            {"description": "a small yellow duck that holds its aching head"},
            422,
            "web_pictures_words",
        ),
    ],
)
def test_a_picture_search_out_of_shape_is_refused_before_anything_is_queued(
    api, body, status, code
) -> None:
    client, repository = _client(api)
    refused = _ask(client, **body)
    assert (refused.status_code, refused.json()["code"]) == (status, code)
    count = (
        repository.connection.cursor(row_factory=tuple_row)
        .execute("select count(*) from reference_request")
        .fetchone()[0]
    )
    assert count == 0


@pytest.mark.postgres
def test_picture_searches_are_off_unless_turned_on(api) -> None:
    client = api[0]()
    listed = _read(client, "/worlds/references").json()
    assert listed["web_pictures"] == {
        "offered": False,
        "code": "web_pictures_not_offered",
        "words": 8,
    }
    refused = _ask(client)
    assert (refused.status_code, refused.json()["code"]) == (409, "web_pictures_not_offered")
    # An ordinary web request is still offered.
    assert _ask(client, web_pictures=False).status_code == 202


@pytest.mark.parametrize(
    ("value", "on"), [(None, False), ("", False), ("off", False), ("on", True), (" YES ", True)]
)
def test_picture_searches_are_off_unless_set_on(value, on) -> None:
    assert searches_web_pictures_here(value) is on


def test_an_unrecognised_picture_search_setting_stops_startup() -> None:
    with pytest.raises(ReferenceSettingRefused) as refused:
        searches_web_pictures_here("sometimes")
    assert refused.value.variable == "EXULANICA_REFERENCE_WEB_PICTURES"
