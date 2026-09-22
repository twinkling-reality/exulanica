"""PG18 evidence that a saved world a person owns can hold deterministic inhabitants.

The walk is the product one: make a starter world, put a reviewed object with a rest
affordance in it, register that world with the host, create a society, direct one inhabitant to
rest, advance one simulated minute and read the outcome back through a runtime built again from
nothing. No district, no admitted city source and no model take part.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.api.services import (
    AUTHORED_WORLDS_PROFILE,
    SOCIETY_AUTHORED_WORLDS_ENV,
    build_services,
)
from exulanica.api.society_runtime import AuthoredWorldSocietyBinding, SocietyRuntime
from exulanica.selection.validation import Session
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import BLOB_NAMESPACE
from exulanica.world.assets import reviewed_assets, seed_reviewed_assets
from exulanica.world.models import DEFAULT_WORLD_ID
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_action_repository import SocietyActionRepository
from exulanica.world.society_actions import ActionIntent
from exulanica.world.society_authored_ground import LATTICE_MM, NAVIGATION_PROFILE
from exulanica.world.society_composition import reviewed_affordance_registry
from exulanica.world.society_input_policy import AUTHORED_GROUND_INPUT
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.starter import (
    AUTHORED_GROUND_MODULE_VERSION,
    AUTHORED_GROUND_V1_MODULE_VERSION,
    AUTHORED_GROUND_V1_STREAMING_KEY,
    AUTHORED_STARTER_ELEMENT_ID,
    AUTHORED_STARTER_REGION_ID,
    _authored_starter_candidate,
    create_starter_authorities,
)
from exulanica.world.structure_repository import WorldStructureRepository

from world_structure_fixtures import structural_candidate

pytestmark = pytest.mark.postgres
SEED = "7a" * 32


def make_starter(connection, workspace, actor, world_id, module_version):
    """A saved starter world at one ground module version.

    Version 2 is what saving a starter makes now, through the product's own function. Version 1
    is what a world saved before the ground stopped stating an edge still holds; nothing creates
    one any more, so this writes the snapshot the starter authority pins for that version and
    then does exactly what ``create_starter_authorities`` does with it.
    """
    if module_version == AUTHORED_GROUND_MODULE_VERSION:
        snapshot_id, _, version_id = create_starter_authorities(
            connection,
            workspace_id=workspace,
            actor=actor,
            title="A world of my own",
            world_id=world_id,
        )
        return snapshot_id, version_id
    structures = WorldStructureRepository(connection, workspace, world_id=world_id)
    preview = structures.preview(
        _authored_starter_candidate(
            world_id,
            module_version=AUTHORED_GROUND_V1_MODULE_VERSION,
            streaming_key=AUTHORED_GROUND_V1_STREAMING_KEY,
        ),
        proposed_by=actor,
    )
    snapshot = structures.apply(
        preview.preview_id,
        base_snapshot_id=None,
        base_graph_sha256=None,
        base_reconstruction_sha256=None,
        committed_by=actor,
    )
    style = WorldStyleRepository(connection, workspace, world_id=world_id).current()
    version = WorldObjectRepository(connection, workspace, world_id=world_id).create_version(
        source_snapshot_id=snapshot.snapshot_id,
        title="A world of my own",
        style_version_id=style.version_id,
        created_by=actor,
    )
    return snapshot.snapshot_id, version.version_id


@pytest.fixture(
    params=[AUTHORED_GROUND_V1_MODULE_VERSION, AUTHORED_GROUND_MODULE_VERSION],
    ids=["bounded-ground-v1", "endless-ground-v2"],
)
def saved_world(repository, tmp_path, request):
    connection = repository.connection
    workspace = repository.workspace_id
    session = Session(workspace_id=workspace, actor=uuid.uuid4())
    store = LocalContentAddressedStore(tmp_path / "blobs")
    seed_reviewed_assets(store)
    world_id = f"world:authored:{uuid.uuid4()}"
    with connection.transaction():
        snapshot_id, version_id = make_starter(
            connection, workspace, session.actor, world_id, request.param
        )
    place = uuid.uuid4()
    connection.execute("insert into place(workspace_id,place_id) values(%s,%s)", (workspace, place))
    binding = AuthoredWorldSocietyBinding(
        binding_id="saved-world-fixture-registration-v1",
        workspace_id=workspace,
        world_id=world_id,
        version_id=version_id,
        source_snapshot_id=snapshot_id,
        place_id=place,
        region_id=AUTHORED_STARTER_REGION_ID,
    )
    registry = reviewed_affordance_registry()
    runtime = SocietyRuntime(
        store=store, authored_bindings=[binding], reviewed_affordances=registry
    )
    world = {
        "ground_module_version": request.param,
        "connection": connection,
        "workspace": workspace,
        "session": session,
        "store": store,
        "world_id": world_id,
        "binding": binding,
        "registry": registry,
        "runtime": runtime,
        "plate": next(a for a in reviewed_assets() if a.asset_key == "cc0.marker-plate"),
        "pillar": next(a for a in reviewed_assets() if a.asset_key == "cc0.marker-pillar"),
    }
    world["objects"] = objects_repository(world, runtime)
    return world


def objects_repository(world, runtime):
    return WorldObjectRepository(
        world["connection"],
        world["workspace"],
        world_id=world["world_id"],
        store=world["store"],
        on_edit=lambda version_id: runtime.authored_edit(
            world["connection"], world["session"], version_id
        ),
    )


def initial(world, runtime=None):
    binding = world["binding"]
    return (runtime or world["runtime"]).initial_input(
        world["connection"],
        world["session"],
        binding.version_id,
        binding.place_id,
        binding.region_id,
    )


def society_repository(world, runtime=None):
    runtime = runtime or world["runtime"]
    return SocietyRepository(
        world["connection"],
        world["workspace"],
        world_id=world["world_id"],
        input_authorizer=lambda doc: runtime.authorize(world["connection"], world["session"], doc),
    )


def action_repository(world, runtime=None):
    runtime = runtime or world["runtime"]
    return SocietyActionRepository(
        world["connection"],
        world["workspace"],
        world_id=world["world_id"],
        input_authorizer=lambda doc: runtime.authorize(world["connection"], world["session"], doc),
    )


def place_object(world, asset, object_id, x_mm, z_mm):
    version = world["objects"].version(world["binding"].version_id)
    return world["objects"].add_object(
        version.version_id,
        AuthoredObject(
            object_id=object_id,
            asset_sha256=asset.content_sha256,
            region_id=AUTHORED_STARTER_REGION_ID,
            transform=Transform(x_mm=x_mm, y_mm=0, z_mm=z_mm, yaw_microradians=0, scale_milli=1000),
            origin=ObjectOrigin("authored", "fictional"),
        ),
        base_state_sha256=version.state_sha256,
        actor=world["session"].actor,
    )


def create_society(world, profile="exulanica-society/v2"):
    binding = world["binding"]
    document = initial(world)
    society = society_repository(world).create(
        binding.version_id,
        place_id=binding.place_id,
        region_id=binding.region_id,
        seed=SEED,
        actor=world["session"].actor,
        profile=profile,
        initial_input=document,
    )
    return society, document


def test_an_empty_starter_has_a_walkable_area_and_nothing_to_do_in_it(saved_world):
    document = initial(saved_world)
    navigation = document["navigation"]
    assert document["profile"] == AUTHORED_GROUND_INPUT
    assert document["availability"] == "available"
    assert navigation["profile"] == NAVIGATION_PROFILE
    assert document["frame"]["name"] == "authored-ground-local-mm"
    # The ground states no surveyed origin, because a saved world was never measured anywhere.
    assert "origin_crs84_e7" not in document["frame"]
    assert {node["subject_id"] for node in navigation["nodes"]} == {AUTHORED_STARTER_ELEMENT_ID}
    # A world saved on the bounded ground walks the extent its ground states. A world saved on
    # the endless ground walks an area the society declared, and says so; either way the lattice
    # is the same size.
    area = navigation["walkable_area"]
    expected = {1: "ground", 2: "declared"}[saved_world["ground_module_version"]]
    assert area["source"] == expected
    assert len(navigation["nodes"]) == 121 and len(navigation["edges"]) == 220
    span = max(node["position_mm"][0] for node in navigation["nodes"])
    assert span <= area["half_width_mm"] - navigation["clearance_mm"]
    assert span + LATTICE_MM > area["half_width_mm"] - navigation["clearance_mm"]
    # A ground declares a place to stand, never an activity. Until the person puts something in
    # the world there is nothing for an inhabitant to do, and creation says so rather than
    # inventing a destination out of the spawn point.
    assert navigation["destinations"] == [] and document["targets"] == []
    with pytest.raises(ValueError, match="reachable targets"):
        create_society(saved_world)


@pytest.mark.parametrize("profile", ["exulanica-society/v2", "exulanica-society/v3"])
def test_a_rest_object_makes_a_starter_world_inhabitable_and_survives_reload(saved_world, profile):
    world = saved_world
    place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    society, document = create_society(world, profile)
    [target] = document["targets"]
    assert society["profile"] == profile
    assert target["affordance"] == "rest" and target["origin"] == "authored"
    assert target["object_id"] == "object:cushion"
    # The access node is 1,000 mm east and 1,000 mm south of the cushion: 1,414 mm, inside the
    # reviewed reach, on the bounded and the endless ground alike.
    node = next(n for n in document["navigation"]["nodes"] if n["node_id"] == target["node_id"])
    reach = world["registry"][world["plate"].content_sha256]["reach_mm"]
    squared = (node["position_mm"][0] - 3_000) ** 2 + (node["position_mm"][1] - 5_000) ** 2
    assert squared == 2_000_000 <= reach**2

    subject = uuid.UUID(society["state"]["inhabitants"][0]["id"])
    request_id = uuid.uuid4()
    envelope = action_repository(world).create(
        world["binding"].version_id,
        request_id=request_id,
        requested_by=world["session"].actor,
        subject_id=subject,
        base_tick=society["current_tick"],
        base_state_sha256=society["state_sha256"],
        intent=ActionIntent("perform", target["target_id"], "rest"),
    )
    assert envelope["status"] == "pending" and envelope["consumption"] is None

    advanced = society_repository(world).advance(
        world["binding"].version_id,
        base_tick=society["current_tick"],
        base_state_sha256=society["state_sha256"],
    )
    assert advanced["current_tick"] == 1
    consumed = action_repository(world).read(world["binding"].version_id, request_id)
    assert consumed["status"] == "consumed"
    assert consumed["consumption"] == {"tick": 1, "disposition": "applied"}
    person = next(p for p in advanced["state"]["inhabitants"] if p["id"] == str(subject))
    assert person["goal"]["target_id"] == target["target_id"]
    assert person["explanation"]["summary"].startswith(person["display_name"] + " (simulated)")

    # And the inhabitant actually gets there and rests: it walks the lattice, the three rest
    # ticks run, and the need the rest was for comes down by the reviewed amount.
    need_before = next(p for p in society["state"]["inhabitants"] if p["id"] == str(subject))[
        "need_milli"
    ]
    state = advanced
    for _ in range(12):
        person = next(p for p in state["state"]["inhabitants"] if p["id"] == str(subject))
        if person["action"]["kind"] == "rest" and person["action"]["status"] == "completed":
            break
        state = society_repository(world).advance(
            world["binding"].version_id,
            base_tick=state["current_tick"],
            base_state_sha256=state["state_sha256"],
        )
    else:
        pytest.fail(f"the directed rest never completed: {person['action']}")
    assert person["position_mm"] == node["position_mm"]
    # The need rises by one a tick and a completed rest takes 500 off it, so the whole walk is
    # one arithmetic identity rather than a number that merely looks lower.
    assert person["need_milli"] == need_before + state["current_tick"] - 500
    completions = [
        event
        for event in society_repository(world).events(world["binding"].version_id, limit=256)
        if event["event_kind"] == "action_completed" and str(event["subject_id"]) == str(subject)
    ]
    assert completions and completions[-1]["document"]["synthetic"] is True

    # Reload: a runtime built again from the same registration, and repositories built again
    # from nothing, read the same society and the same record.
    rebuilt = SocietyRuntime(
        store=world["store"],
        authored_bindings=[world["binding"]],
        reviewed_affordances=world["registry"],
    )
    reloaded = society_repository(world, rebuilt).snapshot(world["binding"].version_id)
    assert reloaded["state_sha256"] == state["state_sha256"]
    assert reloaded["current_tick"] == state["current_tick"] > 1
    assert (
        action_repository(world, rebuilt).read(world["binding"].version_id, request_id) == consumed
    )
    assert society_repository(world, rebuilt).replay(world["binding"].version_id)["replay_verified"]


def test_an_accepted_edit_appends_one_input_in_its_own_transaction(saved_world):
    world = saved_world
    place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    society, document = create_society(world)
    assert document["input_seq"] == 1
    place_object(world, world["pillar"], "object:post", -4_000, 1_000)
    inputs = (
        world["connection"]
        .execute(
            "select input_seq,document from world_society_input where workspace_id=%s "
            "and society_id=%s order by input_seq",
            (world["workspace"], society["society_id"]),
        )
        .fetchall()
    )
    assert [row["input_seq"] for row in inputs] == [1, 2]
    latest = inputs[1]["document"]
    assert latest["authored_state"]["edit_seq"] == document["authored_state"]["edit_seq"] + 1
    assert sorted(t["affordance"] for t in latest["targets"]) == ["rest", "visit"]
    # The post blocks navigation, so the lattice edge that would run through it is pruned
    # rather than left in the graph as a route nobody could walk.
    blocked = "ground:-00004000:+00000000|ground:-00004000:+00002000"
    assert blocked in {edge["edge_id"] for edge in document["navigation"]["edges"]}
    assert blocked not in {edge["edge_id"] for edge in latest["navigation"]["edges"]}
    assert latest["navigation"]["nodes"] == document["navigation"]["nodes"]
    assert society_repository(world).replay(world["binding"].version_id)["replay_verified"]


def test_an_unregistered_world_and_a_composed_snapshot_are_refused(saved_world):
    world = saved_world
    absent = SocietyRuntime(
        store=world["store"], authored_bindings=[], reviewed_affordances=world["registry"]
    )
    with pytest.raises(UnavailableSocietyInput, match="not configured"):
        initial(world, absent)
    other = Session(workspace_id=uuid.uuid4(), actor=uuid.uuid4())
    with pytest.raises(UnavailableSocietyInput, match="not configured"):
        world["runtime"].initial_input(
            world["connection"],
            other,
            world["binding"].version_id,
            world["binding"].place_id,
            world["binding"].region_id,
        )
    # A world composed some other way has a ground this profile has not been shown how to read.
    structures = WorldStructureRepository(world["connection"], world["workspace"])
    preview = structures.preview(structural_candidate(), proposed_by=world["session"].actor)
    composed = structures.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=world["session"].actor,
    )
    version = WorldObjectRepository(
        world["connection"], world["workspace"], store=world["store"]
    ).create_version(
        source_snapshot_id=composed.snapshot_id,
        title="Not a starter",
        created_by=world["session"].actor,
    )
    elsewhere = SocietyRuntime(
        store=world["store"],
        authored_bindings=[
            world["binding"].model_copy(
                update={
                    "binding_id": "composed-world",
                    "world_id": DEFAULT_WORLD_ID,
                    "version_id": version.version_id,
                    "source_snapshot_id": composed.snapshot_id,
                }
            )
        ],
        reviewed_affordances=world["registry"],
    )
    with pytest.raises(UnavailableSocietyInput, match="authored ground is unreadable"):
        elsewhere.initial_input(
            world["connection"],
            world["session"],
            version.version_id,
            world["binding"].place_id,
            world["binding"].region_id,
        )


def test_one_version_cannot_be_registered_two_ways(saved_world):
    world = saved_world
    with pytest.raises(ValueError, match="duplicate or conflicting"):
        SocietyRuntime(
            store=world["store"],
            authored_bindings=[world["binding"], world["binding"]],
            reviewed_affordances=world["registry"],
        )


def test_a_registration_file_is_the_only_way_a_saved_world_is_registered(
    saved_world, tmp_path, monkeypatch
):
    world = saved_world
    monkeypatch.setenv("EXULANICA_DATABASE_URL", "postgresql://localhost/unused")
    data_dir = tmp_path / "data"
    monkeypatch.setenv("EXULANICA_DATA_DIR", str(data_dir))
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                "saved-world-configuration-token-long-enough-for-the-floor": {
                    "workspace_id": str(world["workspace"]),
                    "actor": str(world["session"].actor),
                    "permissions": ["world.read"],
                }
            }
        ),
    )
    monkeypatch.delenv("EXULANICA_SOCIETY_AUTHORED_WORLDS", raising=False)

    silent = build_services()
    assert silent.society_runtime is None
    assert any(SOCIETY_AUTHORED_WORLDS_ENV in note for note in silent.warnings)

    registrations = tmp_path / "authored-worlds.json"
    registrations.write_text(
        json.dumps(
            {
                "profile": AUTHORED_WORLDS_PROFILE,
                "worlds": [json.loads(world["binding"].model_dump_json())],
            }
        )
    )
    monkeypatch.setenv("EXULANICA_SOCIETY_AUTHORED_WORLDS", str(registrations))
    configured = build_services()
    assert configured.society_runtime is not None
    assert not any(SOCIETY_AUTHORED_WORLDS_ENV in note for note in configured.warnings)
    # A registration is not a supply of bytes. This instance reads its own blob store, and an
    # instance without the reviewed asset in it says so rather than composing without it.
    place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    unsupplied = initial(world, configured.society_runtime)
    assert unsupplied["availability"] == "unavailable"
    assert "asset bytes are unavailable" in unsupplied["unavailable_reason"]

    # With the same reviewed catalog available, the file produces the same world as a runtime
    # registered by hand, byte for byte.
    seed_reviewed_assets(LocalContentAddressedStore(data_dir / BLOB_NAMESPACE))
    supplied = build_services()
    assert initial(world, supplied.society_runtime) == initial(world)

    registrations.write_text(json.dumps({"profile": "something-else", "worlds": []}))
    with pytest.raises(ValueError, match=AUTHORED_WORLDS_PROFILE):
        build_services()


def test_the_living_society_has_no_place_contract_for_an_authored_ground(saved_world):
    world = saved_world
    place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    with pytest.raises(ValueError, match="no place contract for an authored ground"):
        create_society(world, "exulanica-society/v4")


def test_an_edit_whose_society_cannot_be_recomposed_leaves_the_world_alone(saved_world):
    world = saved_world
    place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    society, _ = create_society(world)
    before = world["objects"].version(world["binding"].version_id)

    # A runtime registered against a region this world's snapshot does not declare. The edit
    # itself is valid; what fails is reaching the society with it, and that is the same
    # transaction, so neither the edit nor an input survives.
    misregistered = SocietyRuntime(
        store=world["store"],
        authored_bindings=[world["binding"].model_copy(update={"region_id": "region:elsewhere"})],
        reviewed_affordances=world["registry"],
    )
    with (
        pytest.raises(UnavailableSocietyInput, match="society scope disagrees"),
        world["connection"].transaction(),
    ):
        objects_repository(world, misregistered).add_object(
            world["binding"].version_id,
            AuthoredObject(
                object_id="object:never-added",
                asset_sha256=world["plate"].content_sha256,
                region_id=AUTHORED_STARTER_REGION_ID,
                transform=Transform(
                    x_mm=-2_000, y_mm=0, z_mm=-2_000, yaw_microradians=0, scale_milli=1000
                ),
                origin=ObjectOrigin("authored", "fictional"),
            ),
            base_state_sha256=before.state_sha256,
            actor=world["session"].actor,
        )

    after = world["objects"].version(world["binding"].version_id)
    assert after.state_sha256 == before.state_sha256 and after.edit_seq == before.edit_seq
    assert [o.object_id for o in after.objects] == ["object:cushion"]
    sequences = (
        world["connection"]
        .execute(
            "select input_seq from world_society_input where workspace_id=%s and society_id=%s",
            (world["workspace"], society["society_id"]),
        )
        .fetchall()
    )
    assert [row["input_seq"] for row in sequences] == [1]
