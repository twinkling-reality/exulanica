"""The four ways a selected city building cannot be asked about, each refused by name.

``POST /selection/ask`` takes a building selected from the independently admitted NYC layer and
answers from the memories a confirmed place bridge ties to it. A selection that is not an admitted
NYC Open Data building, a building record whose identifiers are malformed, a supplied plan with no
bridge to check it against, and a supplied plan for another place are each refused with 422 and a
sentence saying which. The fixture admits one synthetic building and names a memory place, as
``tests/test_companion_content_surface.py`` builds them; the two record-shape cases read the
admitted features through the repository and change one field of what it returns.
"""

from __future__ import annotations

import dataclasses

import pytest
from exulanica.api.app import create_app
from exulanica.environment import EnvironmentRepository
from fastapi.testclient import TestClient

from test_companion_content_surface import TOKEN, place_content

pytestmark = pytest.mark.postgres

__all__ = ["place_content"]

HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _ask(content: dict, body: dict) -> tuple[int, dict]:
    with TestClient(create_app(content["services"], verify=False)) as client:
        response = client.post(
            "/selection/ask",
            params={"world_id": content["world_id"]},
            json=body,
            headers=HEADERS,
        )
    return response.status_code, response.json()


def _question(content: dict, **extra) -> dict:
    return {"question": "What is here?", "city_context": content["city_context"], **extra}


def _content_plan(entity_id: str) -> dict:
    return {
        "intent": "content",
        "place": {"ids": [entity_id]},
        "content": {"scope": "related"},
    }


def _features_read_as(monkeypatch, change) -> None:
    """The repository's own read, with ``change`` applied to the catalog it returns."""
    original = EnvironmentRepository.read_features

    def read_features(self, *args, **kwargs):
        return change(original(self, *args, **kwargs))

    monkeypatch.setattr(EnvironmentRepository, "read_features", read_features)


def test_a_selection_from_another_provider_is_refused(place_content, monkeypatch):
    _features_read_as(monkeypatch, lambda catalog: dataclasses.replace(catalog, provider_key="osm"))
    status, body = _ask(place_content, _question(place_content))
    assert status == 422, body
    assert body["detail"] == "the city selection is not admitted NYC Open Data"


def test_a_building_whose_identifier_is_malformed_is_refused(place_content, monkeypatch):
    def malformed(catalog):
        (feature,) = catalog.features
        return dataclasses.replace(
            catalog, features=({**feature, "provider_feature_id": "doitt_id:0"},)
        )

    _features_read_as(monkeypatch, malformed)
    status, body = _ask(place_content, _question(place_content))
    assert status == 422, body
    assert body["detail"] == "the semantic city feature is malformed"


def test_a_supplied_plan_with_no_bridge_to_check_it_is_refused(place_content):
    plan = _content_plan(place_content["entity_id"])
    status, body = _ask(place_content, _question(place_content, plan=plan))
    assert status == 422, body
    assert body["detail"] == "the supplied plan cannot be verified without a confirmed place bridge"


def test_a_supplied_plan_for_another_place_is_refused(place_content):
    with TestClient(create_app(place_content["services"], verify=False)) as client:
        created = client.post(
            "/selection/place-bridges", json=place_content["bridge"], headers=HEADERS
        )
        assert created.status_code == 201, created.text
    plan = {**_content_plan(place_content["entity_id"]), "intent": "captures", "content": None}
    status, body = _ask(place_content, _question(place_content, plan=plan))
    assert status == 422, body
    assert body["detail"] == "the supplied plan does not match the selected semantic city place"


def test_the_selection_answers_when_nothing_is_wrong(place_content):
    """The control: the same selection, unaltered and with a bridge, is answered."""
    with TestClient(create_app(place_content["services"], verify=False)) as client:
        created = client.post(
            "/selection/place-bridges", json=place_content["bridge"], headers=HEADERS
        )
        assert created.status_code == 201, created.text
    plan = _content_plan(place_content["entity_id"])
    status, body = _ask(place_content, _question(place_content, plan=plan))
    assert status == 200, body
    assert body["plan"]["intent"] == "content"
