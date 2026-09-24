"""A small square in one request: the arrangement catalog, its resolver, and its two routes.

The catalog holds each arrangement to rules that make it usable wherever it stands; the resolver
places it in front of the person, turned to face them, on the society's lattice, or refuses by
name; apply adds each object as an ordinary edit, all or none; and the version's undo takes them
back one at a time, newest first.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from typing import Any

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.grammar.errors import CatalogError
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world.arrangements import (
    ArrangementRefused,
    ArrangementRequest,
    apply_arrangement,
    arrangement_catalog,
    lay_out,
    load_arrangement_catalog,
    placed_at,
    preview_arrangement,
)
from exulanica.world.assets import reviewed_assets, seed_reviewed_assets
from exulanica.world.errors import StaleObjectBase
from exulanica.world.object_catalog import CATALOG_DIRECTORY, world_object_catalog
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import object_document
from exulanica.world.society_authored_ground import LATTICE_MM
from exulanica.world.starter import AUTHORED_SPAWN_X_MM, AUTHORED_SPAWN_Z_MM
from exulanica.world.structure_repository import WorldStructureRepository

import test_society_authored_ground as authored
import test_society_authored_world_postgres as helpers
import test_society_saved_world_api as saved_api
from conftest import scratch_role_database
from test_society_saved_world_objects import second, thing, world
from test_world_objects_postgres import apply_candidate
from tests_support_api import EVERY_PERMISSION
from world_structure_fixtures import structural_candidate
from world_support import registered_world

saved_world = helpers.saved_world
SQUARE = arrangement_catalog().by_key()["small_square"]
ASSETS = {asset.asset_key: asset for asset in reviewed_assets()}
#: A person standing where a starter world puts them, facing its centre (-z): half a turn.
FACING_THE_CENTRE = 3_141_593
ARRIVAL = (AUTHORED_SPAWN_X_MM, AUTHORED_SPAWN_Z_MM)


# -- the catalog -------------------------------------------------------------------------------


def _document() -> dict[str, Any]:
    return json.loads((CATALOG_DIRECTORY / "world-arrangement.v1.json").read_text())


def _load(tmp_path: pathlib.Path, document: dict[str, Any]):
    (tmp_path / "world-arrangement.v1.json").write_text(json.dumps(document))
    return load_arrangement_catalog(tmp_path)


def test_the_published_file_loads_through_the_path_the_refusals_take(tmp_path):
    assert _load(tmp_path, _document()).sha256 == arrangement_catalog().sha256


def _placement(document, index):
    return document["entries"][0]["placements"][index]


CATALOG_REFUSALS = {
    "a kind the object catalog lacks": (
        lambda d: _placement(d, 0).update(kind="fountain"),
        "names no kind",
    ),
    "a placement off the lattice": (
        lambda d: _placement(d, 0).update(x_mm=LATTICE_MM // 2),
        "not on a lattice node",
    ),
    # The stall moved beside the planter seat: their footprints are 500 mm apart.
    "two objects with no room between them": (
        lambda d: _placement(d, 3).update(x_mm=-2000),
        "no room to walk between",
    ),
    # A lamp post moved in front of the tree: 535 mm from the place in front of the tree.
    "a place inside another object's clearance": (
        lambda d: _placement(d, 6).update(x_mm=0, y_mm=2000),
        "within a clearance and a standing radius",
    ),
    "a centre too near the person": (
        lambda d: d["entries"][0]["anchor"].update(distance_mm=6000),
        "less than a lattice spacing",
    ),
    "a citation of nothing declared": (
        lambda d: _placement(d, 0).update(source="declared/nothing"),
        "does not declare",
    ),
    "a declaration nothing cites": (
        lambda d: d["entries"][0]["declared"].update(unused="A sentence no number cites."),
        "nothing cites",
    ),
    "a quarter turn past a whole turn": (
        lambda d: _placement(d, 0).update(quarter_turns=4),
        "quarter_turns",
    ),
}


@pytest.mark.parametrize("case", sorted(CATALOG_REFUSALS))
def test_the_catalog_refuses_by_name(tmp_path, case):
    mutate, match = CATALOG_REFUSALS[case]
    document = _document()
    mutate(document)
    with pytest.raises(CatalogError, match=match):
        _load(tmp_path, document)


# -- usable wherever it stands ------------------------------------------------------------------


@pytest.mark.parametrize("turns", range(4))
def test_every_place_the_square_offers_is_one_an_inhabitant_can_reach(turns):
    """The society's own composition, over the square alone on open ground, at every heading.

    Every placement stands on a lattice node, so the square meets the lattice this way wherever
    it stands; each stated place must be kept, so the square offers its whole capacity.
    """
    anchor = (-2 * LATTICE_MM, -2 * LATTICE_MM)
    objects = [
        thing(
            f"object:{index}-{item.placement.kind.key}",
            ASSETS[item.placement.kind.asset_key],
            item.centre[0],
            item.centre[1],
            yaw=item.yaw_microradians,
        )
        for index, item in enumerate(placed_at(SQUARE, anchor, turns))
    ]
    document = second(authored.endless(), world(*objects))
    assert document["availability"] == "available"
    kept = {t["object_id"]: len(t["place_node_ids"]) for t in document["targets"]}
    for index, placement in enumerate(SQUARE.placements):
        capacity = placement.kind.use.capacity
        object_id = f"object:{index}-{placement.kind.key}"
        if capacity:
            assert kept[object_id] == capacity, object_id
        else:
            assert object_id not in kept
    assert document["unavailable_affordances"] == []


# -- one resolver, two routes -------------------------------------------------------------------

pytestmark_postgres = pytest.mark.postgres


def _as_the_runtime_role(world) -> None:
    """Commit what the fixture built and grant the deployed runtime role, which then reads it."""
    world["connection"].commit()
    provision_runtime_role(world["connection"])
    world["connection"].commit()


def _is_the_runtime_role(connection) -> None:
    """Positive control: the connection is subject to row level security, as a deployment is."""
    role = connection.execute(
        "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
    ).fetchone()
    assert role == {"rolsuper": False, "rolbypassrls": False}, role


@pytest.fixture
def runtime_world(saved_world, spine_schema):
    """The saved world, previewed and written as the deployed runtime role.

    The fixture builds the world on the harness's own connection; every preview, apply,
    placement and undo here goes through a repository on the runtime role's connection instead.
    """
    world = saved_world
    _as_the_runtime_role(world)
    database = scratch_role_database(spine_schema[1], RUNTIME_ROLE)
    with database.session(world["workspace"]) as connection:
        _is_the_runtime_role(connection)
        runtime = world["runtime"]
        yield {
            **world,
            "connection": connection,
            "objects": WorldObjectRepository(
                connection,
                world["workspace"],
                world_id=world["world_id"],
                store=world["store"],
                on_edit=lambda version_id: runtime.authored_edit(
                    connection, world["session"], version_id
                ),
            ),
        }


@pytest.fixture
def runtime_app(saved_world, spine_schema, monkeypatch):
    """The saved world's API connected as the deployed runtime role, with the owner's token."""
    world = saved_world
    _as_the_runtime_role(world)
    database = scratch_role_database(spine_schema[1], RUNTIME_ROLE)
    with database.session(world["workspace"]) as connection:
        _is_the_runtime_role(connection)
    grant = {
        "workspace_id": str(world["workspace"]),
        "actor": str(world["session"].actor),
        "permissions": EVERY_PERMISSION,
    }
    monkeypatch.setenv("EXULANICA_API_TOKENS", json.dumps({saved_api.TOKEN: grant}))
    runtime = SocietyRuntime(
        store=world["store"], authored_bindings=[], reviewed_affordances=world["registry"]
    )

    def make_app():
        return create_app(
            Services(
                database=database,
                readonly_database=database,
                store=world["store"],
                tokens=load_token_directory(),
                executor_shares_the_write_role=True,
                model_client=None,
                society_runtime=runtime,
            ),
            verify=False,
        )

    return world, make_app


def _request(base, **changes) -> ArrangementRequest:
    fields = {
        "base_state_sha256": base.state_sha256,
        "key": SQUARE.key,
        "version": SQUARE.version,
        "viewer_x_mm": ARRIVAL[0],
        "viewer_z_mm": ARRIVAL[1],
        "viewer_yaw_microradians": FACING_THE_CENTRE,
        "origin_role": "fictional",
    }
    return ArrangementRequest(**{**fields, **changes})


def _version(world):
    return world["objects"].version(world["binding"].version_id)


@pytestmark_postgres
def test_a_square_before_the_arrival_point_is_ready_and_named_by_what_it_holds(runtime_world):
    world = runtime_world
    version = _version(world)
    preview = preview_arrangement(world["objects"], version.version_id, _request(version))
    document = preview.document()
    assert document["availability"] == "ready", document
    assert document["arrangement"]["key"] == "small_square"
    assert document["version"]["state_sha256"] == version.state_sha256
    # Half a turn: the centre is 7.5 m toward -z and moves to the nearest lattice node.
    assert document["anchor"] == {"x_mm": 0, "z_mm": -2 * LATTICE_MM, "quarter_turns": 2}
    added = document["would_add"]
    assert [row["asset_key"] for row in added] == [
        placement.kind.asset_key for placement in SQUARE.placements
    ]
    first = version.edit_seq + 1
    assert [row["object_id"] for row in added] == [
        f"small_square-{first}-{index + 1}-{placement.kind.key}"
        for index, placement in enumerate(SQUARE.placements)
    ]
    assert all(row["document"]["transform"]["y_mm"] == 0 for row in added)


@pytestmark_postgres
def test_apply_adds_exactly_what_preview_showed_one_edit_each_and_undo_takes_back_one(
    runtime_world,
):
    world = runtime_world
    repository = world["objects"]
    version = _version(world)
    request = _request(version)
    shown = preview_arrangement(repository, version.version_id, request).document()["would_add"]
    with repository.connection.transaction():
        applied = apply_arrangement(
            repository, version.version_id, request, actor=world["session"].actor
        )
    after = _version(world)
    assert list(applied.object_ids) == [row["object_id"] for row in shown]
    held = {obj.object_id: obj for obj in after.objects}
    for row in shown:
        assert object_document(held[row["object_id"]]) == row["document"]
    assert after.edit_seq == version.edit_seq + len(SQUARE.placements)
    newest = [edit for edit in after.edits if edit.kind == "add_object"][-len(shown) :]
    assert [edit.object_id for edit in newest] == list(applied.object_ids)
    undone = repository.undo(
        version.version_id, base_state_sha256=after.state_sha256, actor=world["session"].actor
    )
    remaining = {obj.object_id for obj in undone.objects}
    assert applied.object_ids[-1] not in remaining
    assert set(applied.object_ids[:-1]) <= remaining


@pytestmark_postgres
def test_a_refusal_part_way_through_apply_writes_nothing(runtime_world, monkeypatch):
    world = runtime_world
    repository = world["objects"]
    version = _version(world)
    calls = []
    real = WorldObjectRepository.add_object

    def fails_third(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            raise StaleObjectBase("the base moved under this test")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(WorldObjectRepository, "add_object", fails_third)
    with pytest.raises(ArrangementRefused) as refused, repository.connection.transaction():
        apply_arrangement(
            repository, version.version_id, _request(version), actor=world["session"].actor
        )
    assert refused.value.reason == "stale_base"
    assert len(calls) == 3
    assert _version(world).state_sha256 == version.state_sha256


def _blocked(world, **changes) -> str | None:
    version = _version(world)
    preview = preview_arrangement(
        world["objects"], version.version_id, _request(version, **changes)
    )
    reason = preview.blocked_reason
    if reason is not None:
        with (
            pytest.raises(ArrangementRefused) as refused,
            world["objects"].connection.transaction(),
        ):
            apply_arrangement(
                world["objects"],
                version.version_id,
                _request(version, **changes),
                actor=world["session"].actor,
            )
        assert refused.value.reason == reason
        assert _version(world).state_sha256 == version.state_sha256
    return reason


@pytestmark_postgres
def test_each_refusal_is_named_the_same_by_preview_and_apply(runtime_world):
    world = runtime_world
    assert _blocked(world, base_state_sha256="0" * 64) == "stale_base"
    assert _blocked(world, key="large_square") == "arrangement_unknown"
    assert _blocked(world, version=SQUARE.version + 1) == "arrangement_unknown"
    # Facing out from near the far edge: the square would stand past it.
    assert (
        _blocked(world, viewer_z_mm=-8_000, viewer_yaw_microradians=FACING_THE_CENTRE)
        == "arrangement_outside_ground"
    )
    # Standing 7.5 m beyond the arrival point, facing it: the square would stand on it.
    assert (
        _blocked(world, viewer_z_mm=ARRIVAL[1] + SQUARE.anchor_distance_mm)
        == "arrangement_covers_arrival"
    )
    assert _blocked(world) is None


def test_a_refusal_carries_only_a_code_clients_are_given_words_for():
    """Every code reaches a client, which holds words for exactly the declared list."""
    with pytest.raises(ValueError, match="not a declared arrangement refusal"):
        ArrangementRefused("arrangement_crowded")


@pytestmark_postgres
def test_an_object_already_standing_there_is_named(runtime_world):
    world = runtime_world
    placed = helpers.place_object(world, world["pillar"], "object:post", 0, -2 * LATTICE_MM)
    version = _version(world)
    preview = preview_arrangement(world["objects"], version.version_id, _request(version))
    # The square would land on the post, which is what it is refused for first; the post's own
    # places, which the tree would also take, are the next rule's to name.
    assert preview.blocked_reason == "arrangement_overlaps"
    assert preview.blocked_detail is not None
    assert "would stand on or beside object:post" in preview.blocked_detail
    assert _blocked(world) == "arrangement_overlaps"
    # With the post taken back, the same request is ready: the post was the reason.
    world["objects"].undo(
        placed.version_id, base_state_sha256=placed.state_sha256, actor=world["session"].actor
    )
    assert _blocked(world) is None


#: How far in front of a bench its middle place stands, as the catalog derives it.
_BENCH_PLACE_OUT_MM = world_object_catalog().by_key()["bench"].use.places[1][1]


@pytestmark_postgres
@pytest.mark.parametrize("case", ["a post beside its place", "a place beside its place"])
def test_a_square_that_would_take_a_place_people_use_is_named(runtime_world, case):
    """A bench already there keeps the places people use it at, so the square is refused.

    A bench unturned faces -z, its middle place straight in front. Beside a lamp post the bench's
    middle place is 110 mm from the post, inside the clearance the society keeps a place from
    anything that blocks; in front of the tree it is 600 mm from the tree's own place, inside a
    standing spacing. Neither bench is within two clearances of the square, so the rule for
    landing on an object passes both, and the refusal names the places.
    """
    world = runtime_world
    layout = lay_out(
        SQUARE,
        viewer_x_mm=ARRIVAL[0],
        viewer_z_mm=ARRIVAL[1],
        viewer_yaw_microradians=FACING_THE_CENTRE,
        spacing_mm=LATTICE_MM,
    )
    if case == "a post beside its place":
        post = max(
            (item for item in layout.objects if item.placement.kind.key == "lamp_post"),
            key=lambda item: item.centre[0],
        )
        x, place_z = post.centre[0], post.footprint[3] + 110
    else:
        tree = next(item for item in layout.objects if item.placement.kind.key == "planter_tree")
        toward_the_person = max(tree.places, key=lambda place: place[1])
        assert toward_the_person[0] == tree.centre[0]
        x, place_z = toward_the_person[0], toward_the_person[1] + 600
    bench = helpers.place_object(
        world, ASSETS["cc0.bench"], "object:bench", x, place_z + _BENCH_PLACE_OUT_MM
    )
    version = _version(world)
    preview = preview_arrangement(world["objects"], version.version_id, _request(version))
    assert preview.blocked_reason == "arrangement_overlaps"
    assert preview.blocked_detail is not None
    assert "where people use object:bench" in preview.blocked_detail
    assert _blocked(world) == "arrangement_overlaps"
    # The same bench a metre farther off leaves every place alone, and the square is ready.
    world["objects"].undo(
        bench.version_id, base_state_sha256=bench.state_sha256, actor=world["session"].actor
    )
    helpers.place_object(
        world, ASSETS["cc0.bench"], "object:bench-2", x, place_z + 1_000 + _BENCH_PLACE_OUT_MM
    )
    assert _blocked(world) is None


@pytestmark_postgres
def test_a_server_that_does_not_hold_the_bytes_says_so(runtime_world, tmp_path):
    world = runtime_world
    empty = WorldObjectRepository(
        world["connection"],
        world["workspace"],
        world_id=world["world_id"],
        store=LocalContentAddressedStore(tmp_path / "empty"),
    )
    version = _version(world)
    preview = preview_arrangement(empty, version.version_id, _request(version))
    assert preview.blocked_reason == "asset_bytes_unavailable"


@pytestmark_postgres
def test_a_world_not_standing_on_an_authored_ground_is_refused(repository, tmp_path):
    world_id = registered_world(repository.connection, repository.workspace_id)
    structures = WorldStructureRepository(
        repository.connection, repository.workspace_id, world_id=world_id
    )
    snapshot = apply_candidate(structures, structural_candidate())
    store = LocalContentAddressedStore(tmp_path / "store")
    seed_reviewed_assets(store)
    objects = WorldObjectRepository(
        repository.connection, repository.workspace_id, world_id=world_id, store=store
    )
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="A place", created_by=uuid.uuid4()
    )
    preview = preview_arrangement(objects, version.version_id, _request(version))
    assert preview.blocked_reason == "arrangement_needs_authored_ground"


# -- the routes -------------------------------------------------------------------------------


def _body(client, world, **changes):
    scope, version, _ = saved_api.routes(world)
    base = client.get(version, headers=saved_api.OWNER, params=scope).json()["state_sha256"]
    body = {
        "base_state_sha256": base,
        "arrangement_key": SQUARE.key,
        "arrangement_version": SQUARE.version,
        "viewer": {"x_mm": ARRIVAL[0], "z_mm": ARRIVAL[1], "yaw_microradians": FACING_THE_CENTRE},
        "origin_role": "fictional",
    }
    return scope, version, {**body, **changes}


@pytestmark_postgres
def test_the_routes_preview_then_apply_and_inhabitants_brought_in_use_the_square(runtime_app):
    from fastapi.testclient import TestClient

    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        scope, version, body = _body(client, world)
        preview = client.post(
            version + "/arrangements/preview", headers=saved_api.OWNER, params=scope, json=body
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["availability"] == "ready"
        applied = client.post(
            version + "/arrangements/apply", headers=saved_api.OWNER, params=scope, json=body
        )
        assert applied.status_code == 201, applied.text
        answer = applied.json()
        assert answer["arrangement"]["key"] == "small_square"
        assert answer["added_object_ids"] == [
            row["object_id"] for row in preview.json()["would_add"]
        ]
        # Asking again from the same place: the square is already there.
        _, _, again = _body(client, world)
        refused = client.post(
            version + "/arrangements/apply", headers=saved_api.OWNER, params=scope, json=again
        )
        assert refused.status_code == 409
        assert refused.json() == {"code": "arrangement_refused", "detail": "arrangement_overlaps"}
        # The square brought nobody in; the person asks, and the society uses what it holds.
        brought = saved_api.bring_inhabitants(client, world)
        assert brought.status_code in (200, 201), brought.text
        rows = (
            world["connection"]
            .execute(
                "select document from world_society_input where workspace_id=%s "
                "order by input_seq desc limit 1",
                (world["workspace"],),
            )
            .fetchall()
        )
        world["connection"].commit()
        targets = rows[0]["document"]["targets"]
        used = {t["object_id"] for t in targets if t["origin"] == "authored"}
        offered = {
            object_id
            for object_id in answer["added_object_ids"]
            if not object_id.endswith("lamp_post")
        }
        assert offered <= used


@pytestmark_postgres
def test_a_refused_apply_is_a_conflict_named_by_its_reason(runtime_app):
    from fastapi.testclient import TestClient

    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        scope, version, body = _body(client, world, base_state_sha256="0" * 64)
        response = client.post(
            version + "/arrangements/apply", headers=saved_api.OWNER, params=scope, json=body
        )
        assert response.status_code == 409
        assert response.json() == {"code": "arrangement_refused", "detail": "stale_base"}


@pytestmark_postgres
def test_apply_in_a_saved_world_advances_its_entry_and_a_stale_entry_writes_nothing(runtime_app):
    """The web client's path: a person's saved world, each write bound to its saved entry."""
    from fastapi.testclient import TestClient

    _world, make_app = runtime_app
    with TestClient(make_app()) as client:
        created = client.post(
            "/world-entries/starter", headers=saved_api.OWNER, json={"title": "My square"}
        )
        assert created.status_code == 200, created.text
        entry = created.json()
        scope = {"world_id": entry["world_id"]}
        path = f"/world/versions/{entry['authored_version_id']}"
        before = client.get(path, headers=saved_api.OWNER, params=scope).json()
        body = {
            "base_state_sha256": before["state_sha256"],
            "arrangement_key": SQUARE.key,
            "arrangement_version": SQUARE.version,
            "viewer": {
                "x_mm": ARRIVAL[0],
                "z_mm": ARRIVAL[1],
                "yaw_microradians": FACING_THE_CENTRE,
            },
            "origin_role": "personal",
        }
        binding = {
            "entry_id": entry["entry_id"],
            "base_revision": entry["revision"],
            "authored_state_sha256": entry["authored_state_sha256"],
            "authored_edit_seq": entry["authored_edit_seq"],
        }
        stale = {**binding, "base_revision": entry["revision"] + 1}
        refused = client.post(
            path + "/arrangements/apply",
            headers=saved_api.OWNER,
            params=scope,
            json={**body, "saved_entry": stale},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "stale_saved_world_entry"
        assert client.get(path, headers=saved_api.OWNER, params=scope).json() == before

        applied = client.post(
            path + "/arrangements/apply",
            headers=saved_api.OWNER,
            params=scope,
            json={**body, "saved_entry": binding},
        )
        assert applied.status_code == 201, applied.text
        answer = applied.json()
        saved = client.get(f"/world-entries/{entry['entry_id']}", headers=saved_api.OWNER).json()
        assert saved["revision"] == entry["revision"] + 1
        assert saved["authored_state_sha256"] == answer["version"]["state_sha256"]
        assert saved["authored_edit_seq"] == answer["version"]["edit_seq"]
        assert answer["version"]["edit_seq"] == entry["authored_edit_seq"] + len(
            answer["added_object_ids"]
        )
        roles = {obj["origin"]["role"] for obj in answer["version"]["objects"]}
        assert roles == {"personal"}


@pytestmark_postgres
def test_a_square_added_while_people_live_there_is_eight_edits_each_noticed(runtime_app):
    """With inhabitants already there, each object is an ordinary edit the society composes."""
    from fastapi.testclient import TestClient

    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        # A society needs somewhere to go before it starts: a plate well clear of the square.
        saved_api.place(client, world, "object:cushion", 9_000, 6_000)
        brought = saved_api.bring_inhabitants(client, world)
        assert brought.status_code in (200, 201), brought.text

        def inputs():
            rows = (
                world["connection"]
                .execute(
                    "select input_seq, document from world_society_input where workspace_id=%s "
                    "order by input_seq",
                    (world["workspace"],),
                )
                .fetchall()
            )
            world["connection"].commit()
            return rows

        before = inputs()
        scope, version, body = _body(client, world)
        applied = client.post(
            version + "/arrangements/apply", headers=saved_api.OWNER, params=scope, json=body
        )
        assert applied.status_code == 201, applied.text
        added = applied.json()["added_object_ids"]
        after = inputs()
        assert len(after) == len(before) + len(added)
        latest = after[-1]["document"]
        assert latest["availability"] == "available"
        used = {t["object_id"] for t in latest["targets"] if t["origin"] == "authored"}
        assert {object_id for object_id in added if not object_id.endswith("lamp_post")} <= used
