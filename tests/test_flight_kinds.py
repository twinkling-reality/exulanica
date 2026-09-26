"""The flight kind catalog: what it refuses, the components migration 0114 pins, and its hosts."""

from __future__ import annotations

import copy
import json
import pathlib
import re
import shutil
from typing import Any

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.world.assets import CC0_TEXTURED_LICENCE_TEXT
from exulanica.world.flight_kinds import (
    CATALOG_DIRECTORY,
    CATALOG_VERSION,
    check_hosts,
    flight_assets,
    flight_kind_catalog,
    load_flight_kind_catalog,
)
from exulanica.world.object_catalog import (
    CATALOG_DIRECTORY as OBJECT_DIRECTORY,
)
from exulanica.world.object_catalog import (
    CATALOG_VERSION as OBJECT_VERSION,
)
from exulanica.world.object_catalog import (
    load_world_object_catalog,
    world_object_catalog,
)

_MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "exulanica" / "migrations"
_FILE = CATALOG_DIRECTORY / f"flight-kind.v{CATALOG_VERSION}.json"
_ROW = re.compile(
    r"\('(?P<key>[a-z][a-z0-9.-]*)','(?P<title>(?:[^']|'')*)',\s*"
    r"'(?P<summary>(?:[^']|'')*)',\s*'model/gltf-binary',\s*"
    r"'(?P<sha>[0-9a-f]{64})',(?P<size>[0-9]+),'CC0-1.0',\s*"
    r"'(?P<licence>[0-9a-f]{64})','(?P<kind>[a-z]+)'\)"
)


def _pinned() -> dict[str, dict[str, str]]:
    (path,) = _MIGRATIONS.glob("0114_*.sql")
    return {match["key"]: match.groupdict() for match in _ROW.finditer(path.read_text())}


def test_migration_0114_pins_every_body_and_wing_the_catalog_generates():
    """If this fails, the migration describes bytes this code no longer produces."""
    pinned = _pinned()
    generated = {asset.asset_key: asset for asset in flight_assets()}
    assert (
        set(pinned)
        == set(generated)
        == {
            key
            for kind in flight_kind_catalog().kinds
            for key in (kind.body_asset_key, kind.wing_asset_key)
        }
    )
    for key, row in pinned.items():
        asset = generated[key]
        assert (row["sha"], int(row["size"])) == (asset.content_sha256, asset.byte_size), key
        assert (row["title"], row["summary"]) == (asset.title, asset.summary)
        assert row["licence"] == asset.licence_sha256
        assert asset.licence_bytes == CC0_TEXTURED_LICENCE_TEXT.encode("utf-8")
        assert row["kind"] == asset.kind.value == "component"


def test_every_hosted_kind_flies_and_its_host_has_perches_to_start_it_on():
    """Positive control for the refusals below: the published catalogs agree."""
    check_hosts(world_object_catalog(), flight_kind_catalog())
    hosted = {host.kind for kind in world_object_catalog().kinds for host in kind.hosts}
    assert hosted == {kind.key for kind in flight_kind_catalog().kinds} == {"small_bird"}


# -- what the loader refuses -------------------------------------------------------------------


def _document() -> dict[str, Any]:
    return json.loads(_FILE.read_text(encoding="utf-8"))


def _load(tmp_path: pathlib.Path, document: dict[str, Any]):
    (tmp_path / _FILE.name).write_text(json.dumps(document), encoding="utf-8")
    return load_flight_kind_catalog(tmp_path)


def test_the_published_file_loads_through_the_path_its_refusals_take(tmp_path):
    assert _load(tmp_path, _document()).sha256 == flight_kind_catalog().sha256


def _bird(document: dict[str, Any]) -> dict[str, Any]:
    return document["entries"][0]


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda e: e.update(module="exulanica-movement/swimming/v1"),
            "unknown movement module 'exulanica-movement/swimming/v1'",
        ),
        (
            lambda e: e.update(module="exulanica-movement/walking/v1"),
            "moves agents of society-engines",
        ),
        (
            lambda e: e.update(module="exulanica-movement/roads/v1"),
            "moves agents of vehicle-class",
        ),
        (
            lambda e: e["parameters"]["cruise_speed_mm_s"].update(value=40_000),
            "cruise_speed_mm_s is an int in",
        ),
        (lambda e: e["parameters"].pop("glide_speed_mm_s"), "states exactly"),
        (
            lambda e: e["parameters"]["max_speed_mm_s"].update(value=4_000),
            "cruise speed is at most max speed",
        ),
        (
            lambda e: e["parameters"]["body_span_mm"].update(value=300),
            "states a span of 300 mm and its body and wings draw 280 mm",
        ),
        (
            lambda e: e["parameters"]["body_span_mm"].update(source="declared/nowhere"),
            "cites declared/nowhere, which it does not declare",
        ),
        (
            lambda e: e["declared"].update(unused="A sentence that no figure cites at all."),
            "declares \\['unused'\\] and no number cites them",
        ),
        (
            lambda e: e["materials"].update(object_secondary="cc0.float-glazing"),
            "admits",
        ),
    ],
    ids=[
        "unknown_module",
        "module_of_another_catalog",
        "unconnected_module",
        "value_outside_the_module_bounds",
        "missing_parameter",
        "cruise_above_max",
        "span_the_body_does_not_draw",
        "undeclared_source",
        "unused_declaration",
        "material_its_role_refuses",
    ],
)
def test_the_loader_refuses_by_name(tmp_path, mutate, match):
    document = _document()
    mutate(_bird(document))
    with pytest.raises(CatalogError, match=match):
        _load(tmp_path, document)


def test_a_file_no_schema_claims_is_refused(tmp_path):
    shutil.copy(_FILE, tmp_path / _FILE.name)
    (tmp_path / "flight-kind.v2.json").write_text("{}", encoding="utf-8")
    with pytest.raises(CatalogError, match="files with no schema"):
        load_flight_kind_catalog(tmp_path)


def _objects_hosting(tmp_path: pathlib.Path, change) -> Any:
    """The object catalog with its current version changed, beside its earlier versions."""
    for earlier in range(1, OBJECT_VERSION):
        name = f"world-object.v{earlier}.json"
        shutil.copy(OBJECT_DIRECTORY / name, tmp_path / name)
    name = f"world-object.v{OBJECT_VERSION}.json"
    document = json.loads((OBJECT_DIRECTORY / name).read_text(encoding="utf-8"))
    tree = next(entry for entry in document["entries"] if entry["key"] == "planter_tree")
    change(tree)
    (tmp_path / name).write_text(json.dumps(document), encoding="utf-8")
    return load_world_object_catalog(tmp_path)


def test_a_host_of_a_kind_that_does_not_fly_is_refused(tmp_path):
    objects = _objects_hosting(tmp_path, lambda tree: tree["hosts"][0].update(kind="dragon"))
    with pytest.raises(CatalogError, match="hosts dragon, which the flight kind catalog"):
        check_hosts(objects, flight_kind_catalog())


def test_a_host_with_too_few_perches_to_start_its_flyers_on_is_refused(tmp_path):
    objects = _objects_hosting(tmp_path, lambda tree: tree["hosts"][0].update(count=6))
    with pytest.raises(CatalogError, match="hosts 6 small_bird and has 5 perches"):
        check_hosts(objects, flight_kind_catalog())


def test_a_perch_narrower_than_a_kind_does_not_count_for_its_hosts(tmp_path):
    def narrow(tree):
        for perch in tree["perches"][2:]:
            perch["span_mm"] = 200

    objects = _objects_hosting(tmp_path, narrow)
    with pytest.raises(CatalogError, match="has 2 perches left at least 280 mm wide"):
        check_hosts(objects, flight_kind_catalog())


def test_the_generated_bodies_are_the_same_bytes_every_time():
    first = [(asset.asset_key, asset.content_sha256) for asset in flight_assets()]
    flight_assets.cache_clear()
    try:
        assert [(asset.asset_key, asset.content_sha256) for asset in flight_assets()] == first
    finally:
        flight_assets.cache_clear()


def test_a_copy_of_the_catalog_is_not_mistaken_for_it(tmp_path):
    document = _document()
    changed = copy.deepcopy(document)
    changed["entries"][0]["summary"] = "A small grey bird."
    assert _load(tmp_path, changed).sha256 != flight_kind_catalog().sha256


def _two_kinds(tmp_path: pathlib.Path, wrens: int):
    """A catalog with a second kind like the small bird, and a tree hosting three small birds and
    ``wrens`` of it."""
    document = _document()
    wren = copy.deepcopy(_bird(document))
    wren.update(key="wren", title="Wren")
    document["entries"].append(wren)
    kinds_directory = tmp_path / "kinds"
    kinds_directory.mkdir(parents=True)
    flying = _load(kinds_directory, document)
    objects_directory = tmp_path / "objects"
    objects_directory.mkdir()
    objects = _objects_hosting(
        objects_directory,
        lambda tree: tree["hosts"].append(
            {"kind": "wren", "count": wrens, "source": tree["hosts"][0]["source"]}
        ),
    )
    return objects, flying


def test_one_object_s_perches_are_one_pool_for_every_kind_it_hosts(tmp_path):
    """Three small birds and three wrens want six perches of a tree's five: refused, though
    each kind alone has perches enough. Three and two fit, each flyer on a perch of its own."""
    import uuid

    from exulanica.world.authored_delta import AlternateVersion, delta_sha256
    from exulanica.world.flight_input import compose_flight_input
    from scripts.measure_flight_bounds import VERSION_ID, WORLD_ID, _assets, _placed, ground

    objects, flying = _two_kinds(tmp_path / "six", 3)
    with pytest.raises(CatalogError, match="hosts 3 wren and has 2 perches left"):
        check_hosts(objects, flying)
    objects, flying = _two_kinds(tmp_path / "five", 2)
    check_hosts(objects, flying)
    placed = (_placed("tree", "cc0.planter-tree", 0, 0, 0, 1000),)
    version = AlternateVersion(
        version_id=VERSION_ID,
        world_id=WORLD_ID,
        source_snapshot_id=uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/pool"),
        parent_version_id=None,
        title="one tree, two kinds",
        style_version_id=None,
        state_sha256=delta_sha256(
            objects=placed, element_overrides=(), environment_instances=(), point_map_instances=()
        ),
        edit_seq=1,
        source_invalidated=False,
        created_by=uuid.UUID(int=1),
        created_at="2026-09-25T00:00:00+00:00",
        objects=placed,
    )
    flight = compose_flight_input(
        world_id=WORLD_ID,
        version=version,
        ground=ground(),
        asset_keys={digest: key for key, digest in _assets().items()},
        objects=objects,
        flying=flying,
    )
    homes = [flyer.home_perch_id for flyer in flight.flyers]
    assert sorted(flyer.kind for flyer in flight.flyers) == ["small_bird"] * 3 + ["wren"] * 2
    assert len(homes) == len(set(homes)) == 5
