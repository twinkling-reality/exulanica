"""People in a world made from photographs: its society stands in one region it names.

A made world states no ground, no spawn and no position (``exulanica.world.composed``). Its entry
in the society ground catalog says what a society over it reads instead: a declared square about
the region origin on the plane its objects stand on, the lattice and population it shares with
the starter through one navigation profile, and arrival at the region origin by rule. The society
stands in the region a creation names; objects in the world's other places are left out of it,
and photographs, which nothing collides with, are nothing it walks around.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import Iterator

import exulanica.api.society_runtime as society_runtime_module
import pytest
from exulanica.api.app import create_app
from exulanica.api.arrival_source import (
    authorized_arrival_descriptor,
    current_arrival_descriptor,
)
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.roles import provision_runtime_role
from exulanica.environment.district_geometry import segment_blocked
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world.arrangements import arrangement_catalog
from exulanica.world.arrival_selection import ArrivalDescriptor
from exulanica.world.assets import reviewed_assets, seed_reviewed_assets
from exulanica.world.authored_delta import AlternateVersion, delta_sha256
from exulanica.world.composed import composed_candidate
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.models import TopologyContract, TopologySourceSlot
from exulanica.world.objects import AuthoredObject, ElementOverride, ObjectOrigin, Transform
from exulanica.world.society_authored_ground import (
    DECLARED_FLOOR_ELEVATION_MM,
    MADE_WORLD_COMPOSER_VERSIONS,
    NAVIGATION_PROFILE,
    _made_world_ground,
    authored_ground_from_snapshot,
    authored_input_region,
    build_authored_ground_society_input_v3,
    build_authored_ground_society_input_v4,
    ground_navigation,
)
from exulanica.world.society_composition import reviewed_affordance_registry
from exulanica.world.society_grounds import society_ground_for_composer
from exulanica.world.society_planner import validate_society_input
from exulanica.world.structure import SpatialCandidate
from fastapi.testclient import TestClient

import living_square_support as square
import personal_world_support as personal
from character_appearance_fixtures import family
from conftest import scratch_role_database
from tests_support_api import EVERY_PERMISSION

MADE = "atlas-world-composer"
WORLD = "world:personal:made-fixture"
SNAPSHOT = uuid.UUID("5a1d0c4e-5b1a-4b52-8d35-0d0d5c5f0001")
VERSION = uuid.UUID("5a1d0c4e-5b1a-4b52-8d35-0d0d5c5f0002")
PLATE = next(a for a in reviewed_assets() if a.asset_key == "cc0.marker-plate")
PILLAR = next(a for a in reviewed_assets() if a.asset_key == "cc0.marker-pillar")


def _made_candidate(regions: tuple[str, ...] = ("region-a", "region-b")) -> SpatialCandidate:
    slots = tuple(
        TopologySourceSlot(uuid.uuid5(SNAPSHOT, region), f"slot-{region}", region, None, "absent")
        for region in regions
    )
    contract = TopologyContract("d" * 64, regions, slots, world_id=WORLD)
    return composed_candidate(contract, "a" * 64, "b" * 64)


def _read(candidate: SpatialCandidate, region: str | None, **changes):
    arguments = {
        "world_id": WORLD,
        "snapshot_id": SNAPSHOT,
        "snapshot_sha256": "c" * 64,
        "composer_key": candidate.composer_key,
        "composer_version": candidate.composer_version,
        "topology": candidate.topology,
        "placement": candidate.placement,
        "region_id": region,
    }
    return authored_ground_from_snapshot(**(arguments | changes))


def _placed(object_id: str, region: str, x_mm: int, z_mm: int, asset=PLATE) -> AuthoredObject:
    return AuthoredObject(
        object_id=object_id,
        asset_sha256=asset.content_sha256,
        region_id=region,
        transform=Transform(x_mm, 0, z_mm, 0, 1000),
        origin=ObjectOrigin("authored", "fictional"),
    )


def _version(*objects: AuthoredObject, overrides=()) -> AlternateVersion:
    return AlternateVersion(
        version_id=VERSION,
        world_id=WORLD,
        source_snapshot_id=SNAPSHOT,
        parent_version_id=None,
        title="From my photographs",
        style_version_id=None,
        state_sha256=delta_sha256(
            objects=objects,
            element_overrides=overrides,
            environment_instances=(),
            point_map_instances=(),
            things=(),
        ),
        edit_seq=len(objects) + len(overrides),
        source_invalidated=False,
        created_by=uuid.uuid4(),
        created_at="2026-09-27T00:00:00+00:00",
        objects=objects,
        element_overrides=tuple(overrides),
    )


def _compose(ground, version):
    return build_authored_ground_society_input_v3(
        ground=ground,
        version=version,
        input_seq=1,
        dependency_refs=(),
        availability="available",
        unavailable_reason=None,
        reviewed_affordances=reviewed_affordance_registry(),
        segment_blocked=segment_blocked,
        standing=square.STANDING,
    )


def test_new_made_world_input_records_the_served_local_arrival_without_rewriting_v3():
    ground = _read(_made_candidate(), "region-a")
    version = _version()
    before = _compose(ground, version)
    arrival = ArrivalDescriptor.model_validate(
        {
            "profile": "exulanica.arrival-descriptor/v1",
            "presentation_policy": "exulanica.arrival-presentation/v1",
            "region_id": "region-a",
            "position_local_mm": [5000, 1600, 7000],
            "forward_local_millionths": [0, 0, -1000000],
            "source": {
                "profile": "exulanica.arrival-photograph-pin/v1",
                "world_id": WORLD,
                "version_id": str(VERSION),
                "source_snapshot_id": str(SNAPSHOT),
                "region_id": "region-a",
                "capture_id": str(uuid.uuid4()),
            },
        }
    )
    after = build_authored_ground_society_input_v4(
        ground=ground,
        version=version,
        arrival=arrival,
        input_seq=1,
        dependency_refs=(),
        availability="available",
        unavailable_reason=None,
        reviewed_affordances=reviewed_affordance_registry(),
        segment_blocked=segment_blocked,
        standing=square.STANDING,
    )
    assert before == _compose(ground, version)
    assert before["navigation"]["arrival_mm"] == [0, 0]
    assert after["navigation"]["arrival_mm"] == [5000, 7000]
    assert after["arrival"] == arrival.model_dump(mode="json")
    assert before["profile"] == "exulanica.society-input/authored-ground-v3"
    assert after["profile"] == "exulanica.society-input/authored-ground-v4"


def test_a_made_worlds_ground_is_its_catalog_entry_about_the_named_region():
    candidate = _made_candidate()
    assert (candidate.composer_key, candidate.composer_version) == (MADE, 1)
    assert candidate.composer_version in MADE_WORLD_COMPOSER_VERSIONS
    entry = society_ground_for_composer(MADE)
    ground = _read(candidate, "region-b")
    assert entry.arrival == "region_origin" and entry.navigation_profile == NAVIGATION_PROFILE
    assert (ground.region_id, ground.element_id, ground.ground_kind) == (
        "region-b",
        None,
        "unstated",
    )
    assert (
        ground.support_id == "plane:region-b" and ground.elevation_mm == DECLARED_FLOOR_ELEVATION_MM
    )
    assert (ground.arrival_x_mm, ground.arrival_z_mm) == (0, 0)
    assert ground.area.document() == {
        "source": "declared",
        "centre_mm": [0, 0],
        "half_width_mm": entry.declared_half_extent_mm,
        "half_depth_mm": entry.declared_half_extent_mm,
    }
    assert ground.world_region_ids == ("region-a", "region-b")


@pytest.mark.parametrize(
    ("region", "changes", "message"),
    [
        (None, {}, "names the region it stands in"),
        ("region-c", {}, "states no region 'region-c'"),
        ("region-a", {"composer_version": 2}, "composer version 2"),
        ("region-a", {"composer_key": "another-composer"}, "another-composer"),
    ],
    ids=["no-region", "unknown-region", "unread-version", "unknown-composer"],
)
def test_what_a_made_world_does_not_state_is_refused_by_name(region, changes, message):
    with pytest.raises(InvalidStructuralData, match=message):
        _read(_made_candidate(), region, **changes)


def test_an_element_somebody_would_collide_with_is_refused():
    candidate = _made_candidate()
    topology = json.loads(json.dumps(candidate.topology))
    topology["elements"][0]["collision"] = {"kind": "box"}
    with pytest.raises(InvalidStructuralData, match="element that collides"):
        _read(dataclasses.replace(candidate, topology=topology), "region-a")


def test_the_society_walks_its_region_and_leaves_the_worlds_other_places_out():
    ground = _read(_made_candidate(), "region-a")
    here = _placed("object:here", "region-a", 3_000, 5_000)
    there = _placed("object:there", "region-b", 3_000, 5_000)
    hidden = ElementOverride(
        element_id=f"element:source:{uuid.uuid5(SNAPSHOT, 'region-a')}",
        suppressed=True,
        transform=None,
    )
    document = _compose(ground, _version(here, there, overrides=(hidden,)))
    validate_society_input(document)
    assert document["availability"] == "available", document["unavailable_reason"]
    assert authored_input_region(document) == "region-a"
    assert {target["object_id"] for target in document["targets"]} == {"object:here"}
    assert not any(r["object_id"] == "object:there" for r in document["unavailable_affordances"])
    navigation = document["navigation"]
    assert navigation["arrival_mm"] == [0, 0]
    assert navigation["walkable_area"]["source"] == "declared"
    lattice = [node for node in navigation["nodes"] if not node["node_id"].startswith("place:")]
    assert lattice and {node["subject_id"] for node in lattice} == {"plane:region-a"}
    # The same objects over the other region: the other place's object is the one it can use.
    other = _compose(_read(_made_candidate(), "region-b"), _version(here, there))
    assert {target["object_id"] for target in other["targets"]} == {"object:there"}


def test_another_places_objects_are_no_dependency_and_their_assets_decide_nothing_here():
    """Region B's objects are not bound in region A's input, and an asset no reviewed row states
    in B leaves A's input available; the same asset in A still makes A's unavailable."""
    ground = _read(_made_candidate(), "region-a")
    here = _placed("object:here", "region-a", 3_000, 5_000)
    unreviewed = dataclasses.replace(
        _placed("object:unreviewed", "region-b", 3_000, 5_000), asset_sha256="e" * 64
    )
    document = _compose(ground, _version(here, unreviewed))
    assert document["availability"] == "available", document["unavailable_reason"]
    bound = {(ref["kind"], ref["identity"]) for ref in document["dependency_refs"]}
    assert ("authored_object", f"{VERSION}:object:here") in bound
    assert not any("object:unreviewed" in identity for _, identity in bound)
    moved = dataclasses.replace(unreviewed, region_id="region-a")
    refused = _compose(ground, _version(here, moved))
    assert refused["unavailable_reason"] == "unknown_active_asset:object:unreviewed"


def test_a_made_world_reads_its_own_catalog_entrys_lattice():
    """The lattice spacing and navigation profile are the made-world entry's own, not the
    starter's constants: an entry stating others gives a lattice of them."""
    candidate = _made_candidate()
    kind = dataclasses.replace(
        society_ground_for_composer(MADE),
        lattice_mm=4_000,
        navigation_profile="exulanica.test-lattice/v1",
    )
    ground = _made_world_ground(
        kind,
        world_id=WORLD,
        snapshot_id=SNAPSHOT,
        snapshot_sha256="c" * 64,
        composer_key=candidate.composer_key,
        composer_version=candidate.composer_version,
        topology=candidate.topology,
        placement=candidate.placement,
        region_id="region-a",
    )
    navigation = ground_navigation(ground)
    assert (ground.lattice_mm, navigation["profile"]) == (4_000, "exulanica.test-lattice/v1")
    assert {edge["length_mm"] for edge in navigation["edges"]} == {4_000}
    assert ground.document()["lattice_mm"] == 4_000


def test_an_object_in_a_region_the_world_does_not_state_still_makes_the_input_unavailable():
    ground = _read(_made_candidate(), "region-a")
    stray = _placed("object:stray", "region-z", 3_000, 5_000)
    document = _compose(ground, _version(stray))
    assert document["unavailable_reason"] == "unregistered_object_region:object:stray"


# -- through the routes, over a world made from two places ------------------------------------


@pytest.fixture
def made(tmp_path, repository, spine_schema) -> Iterator[personal.Api]:
    """The application as a deployment runs it, with the society runtime every instance builds."""
    _psycopg, scratch = spine_schema
    provision_runtime_role(repository.connection, role=personal.RUNTIME_ROLE)
    provision_runtime_role(repository.connection, role=personal.READER_ROLE, read_only=True)
    database = scratch_role_database(scratch, personal.RUNTIME_ROLE)
    actor = uuid.uuid4()
    grants = {
        personal.OWNER_TOKEN: {
            "workspace_id": str(repository.workspace_id),
            "actor": str(actor),
            "permissions": EVERY_PERMISSION,
        },
        personal.STRANGER_TOKEN: {
            "workspace_id": str(uuid.uuid4()),
            "actor": str(uuid.uuid4()),
            "permissions": EVERY_PERMISSION,
        },
    }
    store = LocalContentAddressedStore(tmp_path / "blobs")
    seed_reviewed_assets(store)
    services = Services(
        database=database,
        readonly_database=scratch_role_database(scratch, personal.READER_ROLE),
        store=store,
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=False,
        model_client=None,
        society_runtime=SocietyRuntime(
            store=store, authored_bindings=[], reviewed_affordances=reviewed_affordance_registry()
        ),
    )
    with TestClient(create_app(services, verify=False)) as client:
        from exulanica.api.routes.character_appearance import CharacterAppearanceRuntime

        client.app.state.services = dataclasses.replace(
            client.app.state.services,
            character_appearance=CharacterAppearanceRuntime(
                (family(),), lambda connection, session, definition: True
            ),
        )
        yield personal.Api(client, repository, store, actor, database)


def _place(api, entry: dict, object_id: str, region: str, asset=PLATE, x_mm=3_000, z_mm=5_000):
    version = api.version(entry)
    placed = api.post(
        f"/world/versions/{entry['authored_version_id']}/objects?world_id={entry['world_id']}",
        {
            "base_state_sha256": version["state_sha256"],
            "object_id": object_id,
            "asset_sha256": asset.content_sha256,
            "region_id": region,
            "transform": {
                "x_mm": x_mm,
                "y_mm": 0,
                "z_mm": z_mm,
                "yaw_microradians": 3_141_593,
                "scale_milli": 1_000,
            },
            "origin_role": "fictional",
            "saved_entry": personal.binding(entry),
        },
    )
    assert placed.status_code == 201, placed.text
    return api.entry(entry["entry_id"])


def _opening_regions(api, entry: dict) -> tuple[str, str]:
    descriptor = current_arrival_descriptor(
        api.repository.connection,
        api.repository.workspace_id,
        entry["world_id"],
        uuid.UUID(entry["authored_version_id"]),
        uuid.UUID(entry["source_snapshot_id"]),
        api.store,
    )
    assert descriptor is not None
    others = {source["region_id"] for source in personal.source_media(api, entry)} - {
        descriptor.region_id
    }
    assert len(others) == 1
    return descriptor.region_id, others.pop()


@pytest.mark.postgres
def test_current_made_world_arrival_is_owned_by_its_saved_source(made):
    api = made
    personal.photograph(api, minute=0)
    personal.photograph(api, minute=0, hour=15)
    personal.group(api)
    entry = personal.make_world(api)
    descriptor = current_arrival_descriptor(
        api.repository.connection,
        api.repository.workspace_id,
        entry["world_id"],
        uuid.UUID(entry["authored_version_id"]),
        uuid.UUID(entry["source_snapshot_id"]),
        api.store,
    )
    assert descriptor is not None
    assert descriptor.source.world_id == entry["world_id"]
    assert descriptor.region_id in {
        source["region_id"] for source in personal.source_media(api, entry)
    }
    assert authorized_arrival_descriptor(
        api.repository.connection, api.repository.workspace_id, descriptor, api.store
    )
    api.repository.insert_tombstone(
        scope="capture",
        capture_id=descriptor.source.capture_id,
        requested_by=api.actor,
        reason="source withdrawn after arrival pin",
    )
    assert not authorized_arrival_descriptor(
        api.repository.connection, api.repository.workspace_id, descriptor, api.store
    )


@pytest.mark.postgres
def test_people_live_in_one_place_of_a_made_world_and_replay(made):
    api = made
    personal.photograph(api, minute=0)
    personal.photograph(api, minute=0, hour=15)
    personal.group(api)
    entry = personal.make_world(api)
    here, there = _opening_regions(api, entry)
    entry = _place(api, entry, "object:bench-here", here)
    entry = _place(api, entry, "object:bench-there", there)
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    # A world of several places needs the place named; one it does not state is refused.
    for region in ("region:starter", "region-nowhere"):
        refused = api.post(society, {"region_id": region, "profile": "exulanica-society/v2"})
        assert refused.status_code == 424, refused.text
        assert "no region" in refused.json()["detail"]
    created = api.post(society, {"region_id": here, "profile": "exulanica-society/v2"})
    assert created.status_code == 200, created.text
    snapshot = created.json()
    assert snapshot["region_id"] == here and snapshot["population_size"] == 8
    input_row = api.repository.connection.execute(
        "select i.document from world_society_input i join world_society s "
        "on s.workspace_id=i.workspace_id and s.society_id=i.society_id "
        "where s.workspace_id=%s and s.version_id=%s and i.input_seq=1",
        (api.repository.workspace_id, uuid.UUID(entry["authored_version_id"])),
    ).fetchone()
    genesis = input_row["document"]
    assert genesis["profile"] == "exulanica.society-input/authored-ground-v4"
    assert genesis["arrival"]["region_id"] == here
    opened = api.entry(entry["entry_id"])
    assert opened["arrival"] == genesis["arrival"]
    assert opened["arrival_unavailable_reason"] is None
    ax, _, az = genesis["arrival"]["position_local_mm"]
    assert (
        min(
            ((person["position_mm"][0] - ax) ** 2 + (person["position_mm"][1] - az) ** 2) ** 0.5
            for person in snapshot["state"]["inhabitants"]
        )
        >= 2_000
    )
    places = api.get(society + "&places=true").json()["places"]
    assert [target["object_id"] for target in places["targets"]] == ["object:bench-here"]
    assert places["walkable_area"]["source"] == "declared"
    steps = society.replace("/society?", "/society/steps?")
    for _ in range(5):
        read = api.get(society).json()
        stepped = api.post(
            steps, {"base_tick": read["current_tick"], "base_state_sha256": read["state_sha256"]}
        )
        assert stepped.status_code == 200, stepped.text
    # An edit in the society's own place reaches it; one elsewhere in the world changes no place.
    entry = api.entry(entry["entry_id"])
    entry = _place(api, entry, "object:pillar-here", here, asset=PILLAR, x_mm=-3_000)
    entry = _place(api, entry, "object:pillar-there", there, asset=PILLAR, x_mm=-3_000)
    read = api.get(society).json()
    stepped = api.post(
        steps, {"base_tick": read["current_tick"], "base_state_sha256": read["state_sha256"]}
    )
    assert stepped.status_code == 200, stepped.text
    after = api.get(society + "&places=true").json()
    assert after["region_id"] == here and after["input_seq"] > 1
    assert sorted(target["object_id"] for target in after["places"]["targets"]) == [
        "object:bench-here",
        "object:pillar-here",
    ]
    replay = api.get(society.replace("/society?", "/society/replay?"))
    assert replay.status_code == 200, replay.text
    assert replay.json()["replay_verified"]
    pinned_capture = uuid.UUID(genesis["arrival"]["source"]["capture_id"])
    api.repository.insert_tombstone(
        scope="capture",
        capture_id=pinned_capture,
        requested_by=api.actor,
        reason="saved arrival source withdrawn",
    )
    unavailable = api.entry(entry["entry_id"])
    assert unavailable["arrival"] is None
    assert unavailable["arrival_unavailable_reason"] == "arrival_source_unavailable"
    held = api.repository.connection.execute(
        "select document from world_society_input where workspace_id=%s and society_id=%s "
        "and input_seq=1",
        (api.repository.workspace_id, uuid.UUID(snapshot["society_id"])),
    ).fetchone()
    assert held["document"] == genesis, "withdrawal does not rewrite immutable input"
    assert replay.json()["state_sha256"] == after["state_sha256"]


@pytest.mark.postgres
def test_another_place_never_reaches_this_society_and_one_version_holds_one(made):
    """An edit in region B appends no input to region A's society, an asset withdrawn in B leaves
    A readable and steppable, an edit in A still reaches it, and a creation naming B is refused by
    name with nothing composed, while one naming A reads the society back, composing nothing."""
    api = made
    personal.photograph(api, minute=0)
    personal.photograph(api, minute=0, hour=15)
    personal.group(api)
    entry = personal.make_world(api)
    here, there = _opening_regions(api, entry)
    entry = _place(api, entry, "object:bench-here", here)
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(society, {"region_id": here, "profile": "exulanica-society/v2"})
    assert created.status_code == 200, created.text
    first = created.json()["input_seq"]
    entry = _place(api, api.entry(entry["entry_id"]), "object:pillar-there", there, asset=PILLAR)
    steps = society.replace("/society?", "/society/steps?")

    def step() -> dict:
        read = api.get(society).json()
        stepped = api.post(
            steps, {"base_tick": read["current_tick"], "base_state_sha256": read["state_sha256"]}
        )
        assert stepped.status_code == 200, stepped.text
        return stepped.json()

    composed = []
    compose = api.client.app.state.society_initial_input
    api.client.app.state.society_initial_input = lambda *args: (
        composed.append(args) or compose(*args)
    )
    connection = api.repository.connection
    licence = connection.execute(
        "select licence_sha256 from world_reviewed_asset where asset_key=%s", (PILLAR.asset_key,)
    ).fetchone()["licence_sha256"]
    try:
        connection.execute(
            # Its licence bytes are no longer the stored ones: the asset is not whole in B.
            "update world_reviewed_asset set licence_sha256=%s where asset_key=%s",
            ("0" * 64, PILLAR.asset_key),
        )
        connection.commit()
        read = api.get(society + "&places=true")
        assert read.status_code == 200, read.text
        assert [t["object_id"] for t in read.json()["places"]["targets"]] == ["object:bench-here"]
        # The edit in B appended nothing: the minute consumes the input the society began with.
        assert step()["input_seq"] == first
        entry = _place(api, api.entry(entry["entry_id"]), "object:plate-here", here, x_mm=-3_000)
        assert step()["input_seq"] == first + 1
        # Composed while B's asset is withdrawn, A's new input is available and uses A's objects.
        after = api.get(society + "&places=true").json()["places"]
        assert after["availability"] == "available", after["unavailable_reason"]
        assert sorted(t["object_id"] for t in after["targets"]) == [
            "object:bench-here",
            "object:plate-here",
        ]
        elsewhere = api.post(society, {"region_id": there, "profile": "exulanica-society/v2"})
        assert elsewhere.status_code == 409, elsewhere.text
        assert elsewhere.json()["code"] == "society_lives_elsewhere"
        again = api.post(society, {"region_id": here, "profile": "exulanica-society/v2"})
        assert again.status_code == 200, again.text
        assert again.json()["society_id"] == created.json()["society_id"]
        assert composed == []
        replay = api.get(society.replace("/society?", "/society/replay?"))
        assert replay.status_code == 200 and replay.json()["replay_verified"], replay.text
    finally:
        api.client.app.state.society_initial_input = compose
        connection.execute(
            "update world_reviewed_asset set licence_sha256=%s where asset_key=%s",
            (licence, PILLAR.asset_key),
        )
        connection.commit()


@pytest.mark.postgres
def test_the_square_stands_in_its_region_whatever_stands_at_the_same_spot_of_another(made):
    """An object at the spot in region B does not stand in the way of the square in region A."""
    api = made
    personal.photograph(api, minute=0)
    personal.photograph(api, minute=0, hour=15)
    personal.group(api)
    entry = personal.make_world(api)
    here, there = sorted({slot["region_id"] for slot in personal.source_media(api, entry)})
    square = arrangement_catalog().by_key()["small_square"]
    viewer = {"x_mm": 0, "z_mm": 4_000, "yaw_microradians": 3_141_593}
    version = f"/world/versions/{entry['authored_version_id']}"
    scope = f"?world_id={entry['world_id']}"

    def preview(region: str) -> dict:
        body = {
            "base_state_sha256": api.version(api.entry(entry["entry_id"]))["state_sha256"],
            "arrangement_key": square.key,
            "arrangement_version": square.version,
            "viewer": {**viewer, "region_id": region},
            "origin_role": "fictional",
        }
        answer = api.post(version + "/arrangements/preview" + scope, body)
        assert answer.status_code == 200, answer.text
        return answer.json()

    # Where the square would stand in B, a bench stands; in A the same spot is clear.
    anchor = preview(there)["anchor"]
    _place(api, entry, "object:bench-there", there, x_mm=anchor["x_mm"], z_mm=anchor["z_mm"])
    blocked = preview(there)
    assert blocked["blocked_reason"] == "arrangement_overlaps", blocked
    ready = preview(here)
    assert ready["availability"] == "ready", ready


@pytest.mark.postgres
def test_a_made_world_serves_its_floor_and_takes_the_small_square_on_it(made):
    """Every region has the declared floor, served on the entry for the app to draw, and the
    small square stands on it in the region the viewer names, where nothing was reconstructed."""
    api = made
    personal.photograph(api, minute=0)
    personal.photograph(api, minute=0, hour=15)
    personal.group(api)
    entry = personal.make_world(api)
    entry_floor = society_ground_for_composer(MADE)
    assert entry["declared_floor"] == {
        "half_extent_mm": entry_floor.declared_half_extent_mm,
        "elevation_mm": DECLARED_FLOOR_ELEVATION_MM,
    }
    here, _there = sorted({slot["region_id"] for slot in personal.source_media(api, entry)})
    square = arrangement_catalog().by_key()["small_square"]
    version = f"/world/versions/{entry['authored_version_id']}"
    scope = f"?world_id={entry['world_id']}"
    body = {
        "base_state_sha256": api.version(entry)["state_sha256"],
        "arrangement_key": square.key,
        "arrangement_version": square.version,
        "viewer": {"x_mm": 0, "z_mm": 4_000, "yaw_microradians": 3_141_593},
        "origin_role": "fictional",
    }
    # With no region named, a world of several regions gives the square no ground to stand on.
    unnamed = api.post(version + "/arrangements/preview" + scope, body)
    assert unnamed.status_code == 200, unnamed.text
    assert unnamed.json()["blocked_reason"] == "arrangement_needs_authored_ground"
    named = {**body, "viewer": {**body["viewer"], "region_id": here}}
    preview = api.post(version + "/arrangements/preview" + scope, named)
    assert preview.status_code == 200 and preview.json()["availability"] == "ready", preview.text
    applied = api.post(
        version + "/arrangements/apply" + scope,
        {**named, "saved_entry": personal.binding(entry)},
    )
    assert applied.status_code == 201, applied.text
    added = applied.json()["added_object_ids"]
    placed = {o["object_id"]: o for o in api.version(api.entry(entry["entry_id"]))["objects"]}
    assert added and all(placed[object_id]["region_id"] == here for object_id in added)
    assert all(
        placed[object_id]["transform"]["y_mm"] == DECLARED_FLOOR_ELEVATION_MM for object_id in added
    )
    society = f"{version}/society{scope}"
    created = api.post(society, {"region_id": here, "profile": "exulanica-society/v2"})
    assert created.status_code == 200, created.text
    targets = api.get(society + "&places=true").json()["places"]["targets"]
    assert {target["object_id"] for target in targets} & set(added)


@pytest.mark.postgres
def test_two_object_arrangement_reuses_arrival_bytes_before_the_asset_lock(made, monkeypatch):
    api = made
    personal.photograph(api, minute=0)
    personal.photograph(api, minute=0, hour=15)
    personal.group(api)
    entry = personal.make_world(api)
    here, _there = _opening_regions(api, entry)
    entry = _place(api, entry, "object:home", here, x_mm=-8_000, z_mm=-8_000)
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(society, {"region_id": here, "profile": "exulanica-society/v2"})
    assert created.status_code == 200, created.text

    runtime = api.client.app.state.services.society_runtime
    original = society_runtime_module.buffer_arrival_authority
    buffers = 0

    def before_lock(connection, workspace, descriptor, store):
        nonlocal buffers
        assert not runtime._transaction_read(connection).locked, "store read under asset lock"
        buffers += 1
        return original(connection, workspace, descriptor, store)

    monkeypatch.setattr(society_runtime_module, "buffer_arrival_authority", before_lock)
    square = arrangement_catalog().by_key()["small_square"]
    version = f"/world/versions/{entry['authored_version_id']}"
    scope = f"?world_id={entry['world_id']}"
    request = {
        "base_state_sha256": api.version(entry)["state_sha256"],
        "arrangement_key": square.key,
        "arrangement_version": square.version,
        "viewer": {"x_mm": 0, "z_mm": 4_000, "yaw_microradians": 3_141_593, "region_id": here},
        "origin_role": "fictional",
    }
    preview = api.post(version + "/arrangements/preview" + scope, request)
    assert preview.status_code == 200 and preview.json()["availability"] == "ready", preview.text
    applied = api.post(
        version + "/arrangements/apply" + scope, {**request, "saved_entry": personal.binding(entry)}
    )
    assert applied.status_code == 201, applied.text
    assert len(applied.json()["added_object_ids"]) >= 2
    assert buffers >= 1
