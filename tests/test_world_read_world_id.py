"""World Read reads the world it is asked for, and has no default world to fall back on.

A workspace can hold a starter world beside the world its photographs build, so a read that
assumed one would answer about the wrong world's regions and say nothing. Both bundle functions
take the world as a required keyword, and the region graph comes from that world's structure.
"""

from __future__ import annotations

import inspect
import uuid

import pytest
from exulanica.graph.world_read import place_read_bundle, world_read_bundle
from exulanica.world import DEFAULT_WORLD_ID, SavedWorldEntryRepository

from test_world_read_bundle import published as imported_published  # noqa: F401


@pytest.fixture(name="published")
def _published_alias(request):
    return request.getfixturevalue("imported_published")


@pytest.mark.parametrize("read", [world_read_bundle, place_read_bundle])
def test_the_world_is_a_required_keyword(read):
    parameter = inspect.signature(read).parameters["world_id"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_the_region_graph_comes_from_the_world_asked_for(published, repository):
    store, _captures, scene_id = published
    starter = SavedWorldEntryRepository(
        repository.connection, repository.workspace_id, store
    ).create_starter(title="Starter", created_by=uuid.uuid4())
    assert starter.world_id != DEFAULT_WORLD_ID

    def region_graph(world_id):
        envelope = world_read_bundle(
            repository.connection, repository.workspace_id, scene_id, store, world_id=world_id
        )
        return envelope["bundle"]["region_graph"]

    in_starter = region_graph(starter.world_id)
    assert (in_starter["state"], in_starter["world_id"]) == ("available", starter.world_id)
    # The starter's regions were built from no photograph, so none of them holds this scene.
    assert in_starter["regions"]
    assert not any(region["holds_this_scene"] for region in in_starter["regions"])
    in_personal = region_graph(DEFAULT_WORLD_ID)
    assert (in_personal["state"], in_personal["world_id"]) == ("unavailable", DEFAULT_WORLD_ID)
