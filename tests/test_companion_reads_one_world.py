"""The Companion answers from the world it is asked in, and from no other world.

Two saved worlds in one workspace stand over one place: the same canonical place, confirmed as the
same memory place, so every part of a content Selection that could return a world's content
matches both. Each world holds an environment instance placed from the same admitted source, a
society whose engine reads no input, with recorded events, and a society that reads inputs, which
the host authorizes. Asked through the real routes in one world, no answer, evidence packet or
content page names the other world, its versions or its societies, and the host is asked to
authorize only the asked world's society inputs. Both ids are minted, so nothing here passes
because of a legacy id.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from dataclasses import dataclass

import pytest
from exulanica.api.app import create_app
from exulanica.api.society_runtime import AuthoredWorldSocietyBinding, SocietyRuntime
from exulanica.selection.validation import Session
from exulanica.world import (
    AuthoredObject,
    EnvironmentPlacement,
    EnvironmentSelection,
    ObjectOrigin,
    SourceAnchor,
    Transform,
    WorldObjectRepository,
)
from exulanica.world.assets import reviewed_assets, seed_reviewed_assets
from exulanica.world.society_composition import reviewed_affordance_registry
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.starter import AUTHORED_STARTER_REGION_ID, create_starter_authorities
from exulanica.world.worlds import AUTHORED_STARTER, new_world_id
from fastapi.testclient import TestClient

import test_companion_content_surface as content_surface

place_content = content_surface.place_content
pytestmark = pytest.mark.postgres

HEADERS = {"Authorization": f"Bearer {content_surface.TOKEN}"}
#: A society engine that reads no input, so its people and events need no host authorization.
READS_NO_INPUT = "exulanica-society/v1"
#: A society engine that reads inputs, which the host authorizes before anything is shown.
READS_INPUTS = "exulanica-society/v2"
#: A reviewed object people can rest on, which gives a saved world's society somewhere to go.
PLATE = next(asset for asset in reviewed_assets() if asset.asset_key == "cc0.marker-plate")


@dataclass(frozen=True)
class World:
    world_id: str
    #: Every version the world holds, and every society in them.
    version_ids: tuple[uuid.UUID, ...]
    society_ids: tuple[uuid.UUID, ...]

    def named_in(self, text: str) -> list[str]:
        """Each identifier of this world that ``text`` contains."""
        identifiers = (self.world_id, *map(str, self.version_ids), *map(str, self.society_ids))
        return [identifier for identifier in identifiers if identifier in text]


@dataclass
class TwoWorlds:
    client: TestClient
    entity_id: str
    first: World
    second: World
    #: The world each society input the host was asked to authorize belongs to, in order.
    authorized: list[str]


def _society_id(version_id: uuid.UUID) -> uuid.UUID:
    """The society a version holds, whose id the repository derives from the version's."""
    return uuid.uuid5(version_id, "exulanica-society/v1")


@pytest.fixture
def two_worlds(place_content, repository):
    connection, workspace = repository.connection, repository.workspace_id
    services = place_content["services"]
    seed_reviewed_assets(services.store)
    actor = uuid.uuid4()
    session = Session(workspace_id=workspace, actor=actor)
    place = uuid.UUID(place_content["bridge"]["canonical_place_id"])
    admission = uuid.UUID(place_content["city_context"]["admission_id"])
    render = connection.execute(
        "select asset_id from derived_environment_asset where workspace_id=%s and admission_id=%s",
        (workspace, admission),
    ).fetchone()["asset_id"]

    made, bindings = [], []
    for label, seed in (("a", "7a" * 32), ("b", "7b" * 32)):
        world_id = new_world_id(AUTHORED_STARTER)
        snapshot_id, style, version_id = create_starter_authorities(
            connection,
            workspace_id=workspace,
            actor=actor,
            title=f"World {label}",
            world_id=world_id,
        )
        objects = WorldObjectRepository(
            connection, workspace, world_id=world_id, store=services.store
        )
        objects.add_environment(
            version_id,
            EnvironmentPlacement(
                instance_id=f"environment:{label}",
                admission_id=admission,
                render_asset_id=render,
                publication_id=None,
                selection=EnvironmentSelection("whole_asset", None, None),
                source_anchor=SourceAnchor("nyc-grid", 1000, (10, 20, 0)),
                region_id=AUTHORED_STARTER_REGION_ID,
                transform=Transform(0, 0, 0, 0, 1000),
                origin=ObjectOrigin("authored", "fictional"),
            ),
            base_state_sha256=objects.version(version_id).state_sha256,
            actor=actor,
        )
        societies = SocietyRepository(connection, workspace, world_id=world_id)
        state = societies.create(
            version_id,
            place_id=place,
            region_id=AUTHORED_STARTER_REGION_ID,
            seed=seed,
            actor=actor,
            profile=READS_NO_INPUT,
        )
        # A simulated minute at a time until somebody departs, which is the event it records.
        while not connection.execute(
            "select 1 from world_society_event where workspace_id=%s and society_id=%s limit 1",
            (workspace, state["society_id"]),
        ).fetchone():
            assert state["current_tick"] < 1440, "a simulated day passed with no departure"
            state = societies.advance(
                version_id, base_tick=state["current_tick"], base_state_sha256=state["state_sha256"]
            )
        reading = objects.create_version(
            source_snapshot_id=snapshot_id,
            title=f"World {label} with inputs",
            style_version_id=style.version_id,
            created_by=actor,
        )
        objects.add_object(
            reading.version_id,
            AuthoredObject(
                object_id="object:cushion",
                asset_sha256=PLATE.content_sha256,
                region_id=AUTHORED_STARTER_REGION_ID,
                transform=Transform(3_000, 0, 5_000, 0, 1000),
                origin=ObjectOrigin("authored", "fictional"),
            ),
            base_state_sha256=reading.state_sha256,
            actor=actor,
        )
        bindings.append(
            AuthoredWorldSocietyBinding(
                binding_id=f"companion-world-{label}",
                workspace_id=workspace,
                world_id=world_id,
                version_id=reading.version_id,
                source_snapshot_id=snapshot_id,
                place_id=place,
                region_id=AUTHORED_STARTER_REGION_ID,
            )
        )
        made.append((world_id, version_id, reading.version_id, seed))

    runtime = SocietyRuntime(
        store=services.store,
        authored_bindings=bindings,
        reviewed_affordances=reviewed_affordance_registry(),
    )
    worlds = []
    for (world_id, version_id, reading_id, seed), binding in zip(made, bindings, strict=True):
        SocietyRepository(
            connection,
            workspace,
            world_id=world_id,
            input_authorizer=lambda document: runtime.authorize(connection, session, document),
        ).create(
            reading_id,
            place_id=place,
            region_id=AUTHORED_STARTER_REGION_ID,
            seed=seed,
            actor=actor,
            profile=READS_INPUTS,
            initial_input=runtime.initial_input(
                connection, session, reading_id, binding.place_id, binding.region_id
            ),
        )
        worlds.append(
            World(
                world_id=world_id,
                version_ids=(version_id, reading_id),
                society_ids=(_society_id(version_id), _society_id(reading_id)),
            )
        )
    connection.commit()

    authorized: list[str] = []
    app = create_app(dataclasses.replace(services, society_runtime=runtime), verify=False)
    with TestClient(app) as client:

        def authorize(connection, session, document):
            authorized.append(document["world_id"])
            return runtime.authorize(connection, session, document)

        app.state.society_input_authorizer = authorize
        confirmed = client.post(
            "/selection/place-bridges", json=place_content["bridge"], headers=HEADERS
        )
        assert confirmed.status_code == 201, confirmed.text
        yield TwoWorlds(client, place_content["entity_id"], worlds[0], worlds[1], authorized)


def _plan(entity_id: str, after=None) -> dict:
    return {
        "intent": "content",
        "place": {"ids": [entity_id]},
        "content": {"scope": "related", "after": after},
    }


def _every_page(worlds: TwoWorlds, world: World) -> list[dict]:
    """Every page of the content Selection asked in ``world``, followed to its end."""
    pages, after = [], None
    while True:
        page = worlds.client.post(
            f"/selection?world_id={world.world_id}",
            json=_plan(worlds.entity_id, after),
            headers=HEADERS,
        )
        assert page.status_code == 200, page.text
        pages.append(page.json())
        after = page.json()["next_page"]
        if after is None:
            return pages


def _asked_in(two_worlds: TwoWorlds, world: World, other: World) -> None:
    """Every executing route, asked in ``world``: its content and none of ``other``'s."""
    two_worlds.authorized.clear()
    in_world = f"?world_id={world.world_id}"
    pages = _every_page(two_worlds, world)
    rows = [row for page in pages for row in page["content"]]
    assert {row["world_id"] for row in rows} - {None} == {world.world_id}
    # The asked world's own content is all there: the instance, both societies' people, and
    # the events the society that reads no input recorded.
    kinds = {row["result_kind"] for row in rows}
    assert {
        "authored_environment_instance",
        "synthetic_inhabitant",
        "simulation_event",
    } <= kinds
    lineage = " ".join(identifier for row in rows for identifier in row["lineage_ids"])
    assert set(world.named_in(lineage)) == {
        world.world_id,
        *map(str, world.version_ids),
        *map(str, world.society_ids),
    }

    answered = two_worlds.client.post(
        f"/selection/ask{in_world}",
        json={"question": "What is here?", "plan": _plan(two_worlds.entity_id)},
        headers=HEADERS,
    )
    packet = two_worlds.client.post(
        f"/selection/packet{in_world}", json=_plan(two_worlds.entity_id), headers=HEADERS
    )
    assert answered.status_code == packet.status_code == 200, (answered.text, packet.text)
    assert world.world_id in answered.text and world.world_id in packet.text
    for response in (answered.text, packet.text, *map(json.dumps, pages)):
        assert other.named_in(response) == []
    # The host was asked about the asked world's society inputs and never the other's.
    assert set(two_worlds.authorized) == {world.world_id}


def test_the_companion_answers_from_the_world_it_is_asked_in_and_names_nothing_of_the_other(
    two_worlds,
):
    _asked_in(two_worlds, two_worlds.first, two_worlds.second)
    _asked_in(two_worlds, two_worlds.second, two_worlds.first)

    # A world this workspace does not hold, and no world at all, are refused before anything
    # is read or anybody's inputs are authorized.
    two_worlds.authorized.clear()
    plan = _plan(two_worlds.entity_id)
    for path in ("/selection", "/selection/packet"):
        unknown = two_worlds.client.post(
            f"{path}?world_id=world:personal:nobody", json=plan, headers=HEADERS
        )
        assert (unknown.status_code, unknown.json()["code"]) == (404, "unknown_reference")
        assert two_worlds.client.post(path, json=plan, headers=HEADERS).status_code == 422
    assert two_worlds.authorized == []
