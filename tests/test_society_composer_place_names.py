"""A place's name allowed for the Companion's photograph answers never reaches its society answers.

A place-name right is granted for a use whose purpose the account holder read
(``exulanica/consent/place-name-uses.v1.json``). The reasoning role's purpose is writing the
Companion's answer to a question about their photographs; an answer about a world's simulated
people is not that, so it must be no use of the right. Its call site replaces every saved name, a
place's included, before anything leaves (``compose_society_answer`` in
``exulanica/selection/society_question.py``), so the boundary has no place's name to release.

Run with every offered use of the place allowed by its namer, through the product's own grant,
as ``tests/test_companion_place_release.py`` allows them.
"""

from __future__ import annotations

import sys

import pytest

from test_companion_place_release import _allow_every_use, _persons_parts
from test_companion_saved_names import PLACE, named
from test_hosted_boundary import SCENARIOS, _body, _unreplaced, run_society_question, world

pytestmark = pytest.mark.postgres

__all__ = ["named", "world"]


def _sent(transport, path: str) -> list[str]:
    return [
        _body(request["payload"])
        for request, sent in zip(transport.requests, transport.paths, strict=True)
        if sent == path
    ]


def test_a_place_allowed_for_every_use_never_reaches_the_society_composer(world):
    allowed = _allow_every_use(world)
    run_society, _ = SCENARIOS["society composer"]
    society = _sent(run_society(allowed), "society composer")
    assert society, "the run never reached the society composer, so it shows nothing"
    for body in society:
        assert PLACE.lower() not in body.lower(), "a place's name reached the society composer"
    assert "[place A]" in society[0], "the question's place was not replaced by its placeholder"

    # Positive control: under the same grants the photograph composer is sent the place's name.
    run_ask, _ = SCENARIOS["composer"]
    composer = _sent(run_ask(allowed), "composer")
    assert any(PLACE.lower() in body.lower() for body in composer)


def test_the_boundary_alone_keeps_an_allowed_place_and_every_person_out(world, monkeypatch):
    """With the society path's own replacement off, the policy its client carries still releases
    no place: the route composes through a client that adds ``no_place_released`` to the
    workspace's (``society_answer_model``)."""
    monkeypatch.setattr(
        sys.modules["exulanica.selection.society_question"], "redact_names", _unreplaced
    )
    run_society, _ = SCENARIOS["society composer"]
    society = _sent(run_society(_allow_every_use(world)), "society composer")
    assert society
    for body in society:
        assert PLACE.lower() not in body.lower(), "a granted place's name reached the composer"
        assert not _persons_parts(body), f"sent {_persons_parts(body)}"


def test_without_the_society_policy_the_grant_would_release_the_place(world, monkeypatch):
    """The control for the two tests above: through the workspace's own client, which releases
    a granted place for the reasoning role, and with the call site's replacement off, the place's
    name does leave. So each layer above is what holds it."""
    monkeypatch.setattr(
        sys.modules["exulanica.selection.society_question"], "redact_names", _unreplaced
    )
    transport = run_society_question(
        _allow_every_use(world),
        client_for=lambda services, connection, workspace: services.hosted_model(
            connection, workspace
        ),
    )
    society = _sent(transport, "society composer")
    assert any(PLACE.lower() in body.lower() for body in society)


def test_the_call_site_alone_keeps_an_allowed_place_out(world):
    """Through the workspace's own client, which would release a granted place for the reasoning
    role, the society path's replacement of every saved name still keeps the place out: each
    layer holds on its own."""
    transport = run_society_question(
        _allow_every_use(world),
        client_for=lambda services, connection, workspace: services.hosted_model(
            connection, workspace
        ),
    )
    society = _sent(transport, "society composer")
    assert society
    for body in society:
        assert PLACE.lower() not in body.lower(), "a granted place's name reached the composer"
