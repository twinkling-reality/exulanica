"""A routine catalog version bump or a newly reviewed asset never breaks a stored society.

A living society records the catalog versions its routine was read from, and a stored input
records the affordance registry it was composed under. Both are versioned data: a new version is
published beside the old one, a stored society keeps reading what it recorded, and a new society
reads the new version. Each test puts a change in place the way a future lane would, and holds a
stored society to advancing and replaying across it.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import uuid

import pytest
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.grammar.catalogs import catalog_digest, load_catalog
from exulanica.grammar.errors import CatalogError
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import society_catalogs, society_composition
from exulanica.world.asset_kinds import AssetKind
from exulanica.world.assets import ReviewedAsset, reviewed_assets, seed_reviewed_assets
from exulanica.world.object_catalog import world_object_catalog
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_catalogs import ROUTINE_DIRECTORY, load_routine_model
from exulanica.world.society_composition import (
    reviewed_affordance_registry,
    validate_recorded_registry,
)
from exulanica.world.society_living import (
    advance_living_society,
    current_routine,
    initial_living_society,
    living_places,
    routine_for,
)

import test_society_authored_ground as authored
import test_society_living_postgres as living_postgres
from society_living_fixtures import SEEDS, grid_input
from test_society_authored_world_postgres import (  # noqa: F401
    create_society,
    objects_repository,
    place_object,
    saved_world,
    society_repository,
)

living = living_postgres.living
objects_api = living_postgres.objects_api
BENCH = ReviewedAsset(
    asset_key="cc0.marker-bench",
    kind=AssetKind.OBJECT,
    title="Marker bench",
    summary="A reviewed asset added after societies were stored, for this test only.",
    payload=b"glTF-bench-standing-in-for-a-new-reviewed-asset",
)


def publish_need_v2(tmp_path, monkeypatch):
    """Publish society-need v2 beside v1, as a routine change is published, and make it current."""
    directory = tmp_path / "society"
    shutil.copytree(ROUTINE_DIRECTORY, directory)
    document = json.loads((directory / "society-need.v1.json").read_text(encoding="utf-8"))
    document["catalog_version"] = 2
    document["entries"][0]["growth_milli_per_tick"] += 1
    (directory / "society-need.v2.json").write_text(json.dumps(document), encoding="utf-8")
    first = society_catalogs.SCHEMAS[("society-need", 1)]
    monkeypatch.setitem(
        society_catalogs.SCHEMAS,
        ("society-need", 2),
        dataclasses.replace(first, catalog_version=2),
    )
    monkeypatch.setattr(society_catalogs, "ROUTINE_DIRECTORY", directory)
    monkeypatch.setitem(society_catalogs.ROUTINE_VERSIONS, "society-need", 2)
    return directory


def test_two_versions_of_a_catalog_sit_side_by_side(tmp_path, monkeypatch):
    before = current_routine()
    place_input = grid_input(version_id=uuid.uuid4())
    [place] = living_places([place_input], before)
    stored = initial_living_society(uuid.UUID(int=4), SEEDS[0], place, before, branch_id="b")
    stored, _ = advance_living_society(stored, SEEDS[0], [place], before)

    directory = publish_need_v2(tmp_path, monkeypatch)
    after = current_routine()
    # A new society reads the new version, and its digest says so.
    assert after.versions["society-need"] == 2 and after.sha256 != before.sha256
    # The stored society reads the version it recorded, and that model is byte for byte the one
    # it was created under, read from a directory that now also holds the new version.
    kept = routine_for(stored)
    assert kept.versions["society-need"] == 1 and kept.sha256 == before.sha256
    assert load_routine_model(directory, versions=before.versions).sha256 == before.sha256
    [again] = living_places([place_input], kept)
    advanced, _ = advance_living_society(stored, SEEDS[0], [again], kept)
    assert advanced["tick"] == 2 and advanced["routine"] == before.binding()
    # The new routine creates a society that records the new version.
    [fresh_place] = living_places([place_input], after)
    fresh = initial_living_society(uuid.UUID(int=5), SEEDS[0], fresh_place, after, branch_id="c")
    assert fresh["routine"]["catalog_versions"]["society-need"] == 2


def test_the_directory_keeps_every_version_a_schema_names(tmp_path, monkeypatch):
    directory = publish_need_v2(tmp_path, monkeypatch)
    (directory / "society-need.v1.json").unlink()
    # Taking the old version out breaks every model, not only the stored society that reads it,
    # so it cannot leave unnoticed.
    with pytest.raises(CatalogError, match="schemas with no file"):
        load_routine_model(directory)


def test_a_version_with_no_schema_is_refused_by_name(tmp_path, monkeypatch):
    # The positive control for the side-by-side rule: replacing a schema instead of adding one
    # beside it, which is all one-schema-per-catalog allowed, strands the stored society.
    publish_need_v2(tmp_path, monkeypatch)
    monkeypatch.delitem(society_catalogs.SCHEMAS, ("society-need", 1))
    (society_catalogs.ROUTINE_DIRECTORY / "society-need.v1.json").unlink()
    with pytest.raises(CatalogError, match="society-need v1 has no schema"):
        load_routine_model(society_catalogs.ROUTINE_DIRECTORY, versions=_versions(need=1))


def _versions(**chosen):
    versions = dict(society_catalogs.ROUTINE_VERSIONS)
    versions.update({f"society-{key}": value for key, value in chosen.items()})
    return versions


def test_released_catalog_versions_never_change_in_place():
    """A released catalog version is replayed by stored societies, so its bytes are fixed.

    Changing the routine means publishing a new version beside it. These are the digests of the
    files released with the living society; a changed file fails here before it fails a replay.
    """
    released = {
        path.name: catalog_digest([load_catalog(path, society_catalogs.SCHEMAS[key])])
        for key in society_catalogs.SCHEMAS
        for path in [ROUTINE_DIRECTORY / f"{key[0]}.v{key[1]}.json"]
    }
    assert current_routine().sha256 == load_routine_model().sha256
    assert released == RELEASED_CATALOGS


#: Read from the files as released with the living society (05120886 and 5acc7cdf), and with the
#: purposeful routine the inputs record; a new version adds a line here, and no line ever changes.
RELEASED_CATALOGS = {
    "society-activity.v1.json": "0ac08e1e351bc93adae7e175f0fe07b46b73ccfcfcefc8e2744b540bd39d3a31",
    "society-capacity.v1.json": "dc9a9a2b337524a3856c69d62626179a8b31587d561b76dff101a4d9f0f93e66",
    "society-need.v1.json": "fde86f793eac317b3899ba384a204e57683773b48ac588c527173511ffccd563",
    "society-policy.v1.json": "789243cd93f0b83274870919df34427fb3b75dc3e8df926cac59d40c2476bb3f",
    "society-purposeful-activity.v1.json": (
        "6e504ccb454c16b359d9a7a9e801bb3a960c3d03281f468bbbe65971cb8c075b"
    ),
    "society-purposeful-activity.v2.json": (
        "2898207d7570d9534cdf1884de58dcf0848c6888b234ff295b6baa8e4ccc1b61"
    ),
    "society-use-class.v1.json": "ba1f7f4971412bf8c612d32ce0144367f237008116d08b78ca19a9b95df9e541",
}


@pytest.mark.postgres
def test_a_catalog_version_bump_leaves_a_stored_living_society_advancing(
    living, tmp_path, monkeypatch
):
    api, _repo, _version, route, _doc, _rights, _body = living
    for _ in range(2):
        living_postgres.step(api, route)
    publish_need_v2(tmp_path, monkeypatch)
    result = living_postgres.step(api, route)
    assert result["current_tick"] == 3
    assert result["state"]["routine"]["catalog_versions"]["society-need"] == 1
    replay = api.get(api.in_world(route + "/replay"))
    assert replay.status_code == 200, replay.text
    assert replay.json()["replay_verified"]


def test_every_reviewed_asset_has_a_society_assignment():
    """A reviewed asset needs a footprint and a use before anybody can place it.

    The world object catalog states both for every kind it generates, and the registry leaves an
    asset it does not state out rather than failing to start, so this is where a gap is found: at
    review, not at the first person who places one.
    """
    registry = reviewed_affordance_registry()
    assert {row["asset_key"] for row in registry.values()} == {
        asset.asset_key for asset in reviewed_assets()
    }


def with_bench(monkeypatch, *, assigned: bool):
    assets = (*reviewed_assets(), BENCH)
    monkeypatch.setattr(society_composition, "reviewed_assets", lambda: assets)
    if assigned:
        catalog = world_object_catalog()
        stated = dataclasses.replace(
            catalog.by_key()["bench"], key="marker_bench", asset_key=BENCH.asset_key
        )
        extended = dataclasses.replace(catalog, kinds=(*catalog.kinds, stated))
        monkeypatch.setattr(society_composition, "world_object_catalog", lambda: extended)


def test_a_newly_reviewed_asset_without_an_assignment_is_left_out_and_refused_by_name(monkeypatch):
    with_bench(monkeypatch, assigned=False)
    registry = reviewed_affordance_registry()
    assert BENCH.content_sha256 not in registry
    assert len(registry) == len(world_object_catalog().kinds)
    placed = authored.placed("object:bench", BENCH, 3_000, 5_000)
    document = authored.compose(authored.ground(), authored.version(placed))
    assert document["unavailable_reason"] == "unknown_active_asset:object:bench"


def test_a_recorded_registry_is_read_by_its_shape_not_by_todays_catalog():
    registry = reviewed_affordance_registry()
    validate_recorded_registry(registry)
    forged = {digest: {**row, "reach_mm": 0} for digest, row in registry.items()}
    with pytest.raises(ValueError, match="recorded society affordance"):
        validate_recorded_registry(forged)


REGISTRY_CHANGES = {
    "reach changed": lambda monkeypatch: reviewed_affordance_registry(reach_mm=1_400),
    "asset reviewed": lambda monkeypatch: (
        with_bench(monkeypatch, assigned=True),
        reviewed_affordance_registry(),
    )[1],
}


@pytest.mark.postgres
@pytest.mark.parametrize("change", sorted(REGISTRY_CHANGES))
def test_a_registry_change_leaves_stored_inputs_authorised(
    saved_world,  # noqa: F811
    monkeypatch,
    tmp_path,
    change,
):
    world = saved_world
    place_object(world, world["plate"], "object:cushion", 3_000, 5_000)
    society, first = create_society(world)
    stepped = society_repository(world).advance(
        world["binding"].version_id,
        base_tick=society["current_tick"],
        base_state_sha256=society["state_sha256"],
    )
    changed = REGISTRY_CHANGES[change](monkeypatch)
    assert changed != world["registry"]
    runtime = SocietyRuntime(
        store=world["store"], authored_bindings=[world["binding"]], reviewed_affordances=changed
    )
    version_id = world["binding"].version_id
    # The stored input names the registry it was composed under, and that one is still held.
    assert (
        society_repository(world, runtime).snapshot(version_id)["state_sha256"]
        == (stepped["state_sha256"])
    )
    world["objects"] = objects_repository(world, runtime)
    place_object(world, world["pillar"], "object:post", -4_000, 1_000)
    moved = society_repository(world, runtime).advance(
        version_id, base_tick=stepped["current_tick"], base_state_sha256=stepped["state_sha256"]
    )
    assert moved["input_seq"] == 2
    rows = (
        world["connection"]
        .execute(
            "select document from world_society_input where workspace_id=%s and society_id=%s "
            "order by input_seq",
            (world["workspace"], society["society_id"]),
        )
        .fetchall()
    )
    recorded = [
        next(
            ref["sha256"]
            for ref in row["document"]["dependency_refs"]
            if ref["kind"] == "society_affordance_registry"
        )
        for row in rows
    ]
    assert recorded[0] != recorded[1]
    assert society_repository(world, runtime).replay(version_id)["replay_verified"]

    # The positive control: an instance that never held the first registry cannot authorise the
    # input composed under it, and says which thing it is missing.
    elsewhere = LocalContentAddressedStore(tmp_path / "elsewhere")
    seed_reviewed_assets(elsewhere)
    stranger = SocietyRuntime(
        store=elsewhere, authored_bindings=[world["binding"]], reviewed_affordances=changed
    )
    with pytest.raises(UnavailableSocietyInput, match="registry this input was composed under"):
        society_repository(world, stranger).replay(version_id)
    assert recorded[0] == next(
        ref["sha256"]
        for ref in first["dependency_refs"]
        if ref["kind"] == "society_affordance_registry"
    )
