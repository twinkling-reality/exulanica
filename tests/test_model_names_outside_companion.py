"""Every route that serves a model's identifier to the page serves its name beside it.

A person reads a model by ``Manifest.model_name``, the one rule; the page prints the served name
and never derives one. The Companion's routes already do (``tests/test_model_names_served.py``);
these are the world style routes, whose versions and proposals the appearance panel shows. The
environment proposal the environment panel shows is held to it in
``tests/test_environment_proposal_placement.py``.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.models.manifest import Role, load_manifest

from test_world_api import world_api  # noqa: F401  (the fixture)

pytestmark = pytest.mark.postgres


def _companion_preview(world_api, model_id: str):  # noqa: F811
    return world_api.post(
        "/world/styles/previews",
        world_api.preview_body(
            origin="companion",
            origin_reference="conversation:names",
            model_id=model_id,
            prompt_version="proposal-1",
            reference_ids=["design-reference:names"],
        ),
    )


def test_a_style_preview_and_its_proposal_name_the_model_as_the_manifest_does(world_api):  # noqa: F811
    manifest = load_manifest()
    drafter = manifest[Role.STRUCTURED_EXTRACTION].primary.model_id
    created = _companion_preview(world_api, drafter)
    assert created.status_code == 201, created.text
    candidate = created.json()["candidate"]
    assert (candidate["model_id"], candidate["model_name"]) == (
        drafter,
        manifest.model_name(drafter),
    )
    assert candidate["model_name"] != drafter
    (listed,) = world_api.get("/world/styles/previews").json()["previews"]
    assert listed["proposal"]["model_name"] == manifest.model_name(drafter)
    assert listed["preview"]["candidate"]["model_name"] == manifest.model_name(drafter)


def test_a_withdrawn_model_is_named_by_its_identifier_and_no_model_by_no_name(world_api):  # noqa: F811
    withdrawn = f"withdrawn/{uuid.uuid4()}"
    created = _companion_preview(world_api, withdrawn)
    assert created.status_code == 201, created.text
    assert created.json()["candidate"]["model_name"] == withdrawn
    assert world_api.current()["current"]["model_name"] is None
