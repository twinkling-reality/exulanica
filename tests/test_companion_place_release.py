"""A place allowed for a Companion role reaches exactly that role's requests, and no person does.

The account holder's rules: a person's saved name never goes to a hosted model, with or without a
right, and a confirmed place's name goes only under a right its namer grants for that place and
that model. The Companion's call sites replace every saved name no right can release and leave a
place's name to the boundary every hosted request passes, with one record of placeholders for the
whole question (``exulanica/selection/request_names.py``); the boundary writes a place it withholds
with the record's placeholder (``exulanica/epistemics/hosted_requests.py``).

These tests run the product through the routes and call paths it runs, over a workspace where a
person and a place are saved through the product's naming path and both are written on a
photograph's sign, and read each request the transport was handed, by the registered path that
sent it (``HOSTED_CALL_PATHS`` in ``tests/test_hosted_boundary.py``). Every decision is recorded
through the product's own grant and withdrawal.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import uuid

import pytest
from exulanica.consent.place_name_rights import grant_place_name, released_place_names
from exulanica.consent.place_names import load_place_name_uses
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.epistemics.hosted_requests import WorkspaceRequestPolicy
from exulanica.identity import IdentityRepository, name_occurrence
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.models.manifest import Role
from exulanica.selection.plan import Intent, SelectionPlan

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, write_photo
from test_companion_saved_names import PERSON, PLACE, named
from test_hosted_boundary import (
    CALL_SITE_REPLACES,
    HOSTED_CALL_PATHS,
    SCENARIOS,
    World,
    _body,
    _unreplaced,
    world,
)
from test_place_name_release_paths import (
    AUTH,
    MANIFEST,
    Instance,
    _carries_the_place,
    _chat,
    _withholds_the_place,
    instance,
)

pytestmark = pytest.mark.postgres

__all__ = ["instance", "named", "world"]

USES = load_place_name_uses()
COMPOSER = Role.REASONING_CHEAP.value
PLANNER = Role.STRUCTURED_EXTRACTION.value

#: A question naming both saved entities, asked in words: the planner and the composer are sent it.
QUESTION = f"Is {PERSON} wearing the running club shirt outside {PLACE}?"

#: A second place saved under a longer name than the fixture's, so the boundary's own order of
#: recognition, longest form first, would number it before the fixture's place.
LONGER_PLACE = "The Old Harbour Lighthouse"


def _ask(instance: Instance, http, question: str, plan: SelectionPlan | None = None) -> dict:
    """``POST /selection/ask`` in the instance's world."""
    body = {"question": question}
    if plan is not None:
        body["plan"] = plan.model_dump(mode="json")
    response = http.post(instance.asking, headers=AUTH, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _user_message(body: str) -> str:
    """The request's user message alone: a system message may quote a line as its own example."""
    (message,) = [m["content"] for m in json.loads(body)["messages"] if m["role"] == "user"]
    return message


# -- the composer's hand-over ----------------------------------------------------------------------


def test_a_place_allowed_for_the_composer_reaches_the_composers_request_and_no_other(instance):
    client, transport = instance.client()
    services = instance.services(client)
    instance.grant(COMPOSER)

    with instance.http(services) as http:
        answer = _ask(instance, http, QUESTION)

    (planned,) = transport.sent_by("planner")
    (composed,) = transport.sent_by("composer")
    assert _carries_the_place(composed)
    # Read from the user message: the composer's own prompt shows the placeholder form by example.
    assert "[place a]" not in _user_message(composed).lower(), "the place also went as a label"
    assert _withholds_the_place(planned), "the planner's hand-over was never allowed"
    # The one record the browser restores names from: each entity, one placeholder.
    assert answer["names"] == {
        "[person A]": str(instance.entities["person"]),
        "[place A]": str(instance.place),
    }


def test_a_stop_holds_the_composers_next_request_back(instance):
    client, transport = instance.client()
    services = instance.services(client)
    instance.grant(COMPOSER)

    with instance.http(services) as http:
        _ask(instance, http, QUESTION)
        instance.withdraw(COMPOSER)
        _ask(instance, http, QUESTION)

    allowed, stopped = transport.sent_by("composer")
    assert _carries_the_place(allowed)
    assert _withholds_the_place(stopped)


def test_a_place_the_planner_is_sent_by_name_is_no_search_term(instance):
    """Allowed for the planner, a place's name may come back in its query, and is removed there.

    A named entity belongs in its own dimension, by id: the text dimension is joined, so the
    place's name as a search term would drop every photograph of it whose text does not spell it.
    The embedding use is allowed too, so the name would reach the query's vector if it stayed.
    """
    client, transport = instance.client()
    transport.by_model[MANIFEST[Role.STRUCTURED_EXTRACTION].primary.model_id] = _chat(
        SelectionPlan(
            intent=Intent.CAPTURES, semantic_query=f"running club at {PLACE}"
        ).model_dump_json()
    )
    services = instance.services(client)
    instance.caption(instance.api_worker(client), instance.photographs[0])
    instance.grant(PLANNER)
    instance.grant()

    with instance.http(services) as http:
        answer = _ask(instance, http, f"Photographs of the running club at {PLACE}")

    (planned,) = transport.sent_by("planner")
    (searched,) = transport.sent_by("query embedding")
    assert _carries_the_place(planned), "the planner was not sent the allowed name"
    assert answer["plan"]["semantic_query"] == "running club at"
    assert json.loads(searched)["input"] == ["running club at"]


# -- one record for the question and its packet ----------------------------------------------------


def _second_place(instance: Instance) -> uuid.UUID:
    """A photograph whose sign names a second place, saved through the product's naming path."""
    payload = json.loads(json.dumps(DEFAULT_PAYLOAD))
    payload["legible_text"] = [
        {"text": LONGER_PLACE.upper(), "is_signage": True, "confidence": "high", "box": None}
    ]
    pipeline = PhotoIngestPipeline(
        instance.repository, instance.store, vision=CountingVisionModel(payload=payload)
    )
    outcome = ingest_observed(
        pipeline,
        instance.repository,
        write_photo(instance.photo_dir, "harbour.jpg", when="2026:08:28 09:00:00"),
    )
    assert outcome.error is None, outcome.error
    occurrence = instance.repository.connection.execute(
        "select occurrence_id from occurrence where workspace_id=%s and capture_id=%s "
        "and class='place'",
        (instance.workspace_id, outcome.capture_id),
    ).fetchone()
    assert occurrence is not None, "the second photograph has no place to name"
    return name_occurrence(
        IdentityRepository(instance.repository.connection, instance.workspace_id),
        AssertionWriter(instance.repository.connection, instance.workspace_id),
        occurrence_id=occurrence["occurrence_id"],
        display_name=LONGER_PLACE,
        actor=instance.session.actor,
    ).entity_id


def test_the_question_and_its_packet_name_each_withheld_place_one_way(instance):
    """The question names one place and the packet's sign another, with a longer name.

    The boundary on its own numbers the longer name first; the composer must instead read each
    place as the request's record names it, which is what the answer's ``names`` say it is.
    """
    longer = _second_place(instance)
    client, transport = instance.client()
    services = instance.services(client)
    plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query="harbour lighthouse")

    with instance.http(services) as http:
        answer = _ask(instance, http, f"Is the running club outside {PLACE}?", plan)

    (composed,) = transport.sent_by("composer")
    message = _user_message(composed)
    question = message.rsplit("Question: ", 1)[1]
    assert question == "Is the running club outside [place A]?"
    assert '"""[place B]"""' in message, "the packet's sign was not the second place's label"
    assert answer["names"]["[place A]"] == str(instance.place)
    assert answer["names"]["[place B]"] == str(longer)


# -- no person, on any path, whatever is allowed ---------------------------------------------------


def _allow_every_use(world: World) -> World:
    """The instance's resolver, and every offered use of the place allowed by its namer."""
    for use in USES.uses:
        grant_place_name(
            world.connection,
            world.repository.workspace_id,
            entity_id=world.entities["place"],
            role=use.role.value,
            notice=USES.notice(use, USES.handoff(use, MANIFEST)),
            actor=world.session.actor,
        )
    world.services = dataclasses.replace(world.services, released_place_names=released_place_names)
    return world


def _persons_parts(body: str) -> list[str]:
    lowered = " ".join(body.lower().split())
    return [part for part in PERSON.lower().split() if part in lowered]


#: The paths whose request the instance's resolver decides, so an allowed place reaches them. The
#: others send under a policy that releases no place: the vision stage's and a society decision's
#: by design, and the caption pass as this run builds it, over a pass given no resolver.
_RELEASING = {
    "planner",
    "composer",
    "request classifier",
    "appearance drafter",
    "environment drafter",
    "query embedding",
}

#: What each run leaves in place: both layers, the boundary with the call site replacing nothing,
#: and the call site with the boundary withholding nothing, which only the paths whose call site
#: replaces names can hold.
LAYERS = {
    "both": (True, True),
    "the boundary alone": (False, True),
    "the call site alone": (True, False),
}


def _cases():
    """Every path with both layers, and each layer alone where the call site is one."""
    for path in sorted(HOSTED_CALL_PATHS):
        yield path, "both"
        if path in CALL_SITE_REPLACES:
            yield path, "the boundary alone"
            yield path, "the call site alone"


def _disable(monkeypatch, *, call_site: bool, boundary: bool) -> None:
    if not call_site:
        monkeypatch.setattr(
            sys.modules["exulanica.selection.request_names"], "redact_names", _unreplaced
        )
    if not boundary:
        monkeypatch.setattr(WorkspaceRequestPolicy, "_withheld", lambda *args, **kwargs: ())


@pytest.mark.parametrize(("path", "layer"), sorted(_cases()))
def test_no_persons_name_leaves_on_any_path_with_every_place_use_allowed(
    world, monkeypatch, path, layer
):
    call_site, boundary = LAYERS[layer]
    _disable(monkeypatch, call_site=call_site, boundary=boundary)
    run, _ = SCENARIOS[path]
    transport = run(_allow_every_use(world))

    bodies = [_body(request["payload"]) for request in transport.requests]
    own = [body for body, sent in zip(bodies, transport.paths, strict=True) if sent == path]
    assert own, f"the {path} run never reached its call site, so it shows nothing"
    for body in bodies:
        assert not _persons_parts(body), f"{path} with {layer}: sent {_persons_parts(body)}"
    if layer == "both" and path in _RELEASING:
        # Positive control: the grants took effect, so the absence above is not a run that
        # sent nobody's name at all.
        assert any(PLACE.lower() in body.lower() for body in own), f"{path} withheld the place"


@pytest.mark.parametrize("path", sorted(CALL_SITE_REPLACES))
def test_with_both_layers_off_the_persons_name_would_leave(world, monkeypatch, path):
    """The control for the test above: its detector sees a person's name when nothing holds it."""
    _disable(monkeypatch, call_site=False, boundary=False)
    run, _ = SCENARIOS[path]
    transport = run(_allow_every_use(world))
    own = [
        _body(request["payload"])
        for request, sent in zip(transport.requests, transport.paths, strict=True)
        if sent == path
    ]
    assert own and any(_persons_parts(body) for body in own), f"{path} carried no person"
