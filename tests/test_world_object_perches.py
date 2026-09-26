"""World object catalog version 3: perches and hosts beside version 2, and nothing else moved.

Version 3 is version 2 with two fields per kind, ``perches`` and ``hosts``, kept out of ``use``,
which is what people do with a kind. Every recipe, size, material and use is version 2's, so the
reviewed rows migrations 0042 and 0105 pinned are the containers version 3 generates
(tests/test_world_object_catalog.py holds those pins against the current version).
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.world.object_catalog import (
    CATALOG_DIRECTORY,
    CATALOG_VERSION,
    load_world_object_catalog,
    world_object_catalog,
)

_V2 = CATALOG_DIRECTORY / "world-object.v2.json"
_V3 = CATALOG_DIRECTORY / "world-object.v3.json"
_NEW_FIELDS = ("perches", "hosts")


def _entries(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


def test_version_3_is_the_version_a_host_reads():
    assert CATALOG_VERSION == 3 == world_object_catalog().version


def test_version_3_without_perches_and_hosts_is_version_2():
    """The parity: take the two new fields and the sentences only they cite out of every entry,
    and what is left is version 2 exactly, entry by entry and field by field."""
    v2, v3 = _entries(_V2), _entries(_V3)
    assert [entry["key"] for entry in v3] == [entry["key"] for entry in v2]
    for old, new in zip(v2, v3, strict=True):
        stripped = {key: value for key, value in new.items() if key not in _NEW_FIELDS}
        stripped["declared"] = {
            key: value for key, value in new["declared"].items() if key not in _NEW_FIELDS
        }
        assert stripped == old, new["key"]


def test_the_loaded_kinds_differ_from_version_2_only_in_perches_and_hosts():
    v2 = load_world_object_catalog(version=2)
    v3 = world_object_catalog()
    for old, new in zip(v2.kinds, v3.kinds, strict=True):
        assert old.perches == old.hosts == ()
        for field in ("key", "asset_key", "title", "summary", "recipe", "dimensions_mm", "use"):
            assert getattr(old, field) == getattr(new, field), (new.key, field)
        assert dict(old.materials) == dict(new.materials)
        assert old.reason == new.reason


def test_perches_and_hosts_are_not_part_of_use():
    for entry in _entries(_V3):
        assert set(entry["use"]) == {"affordance", "blocks_navigation", "places"}


def _crown_top(x: int, y: int) -> int:
    """The tree crown's upper surface over a plan point, by the ellipsoid's own formula."""
    centre, rx, ry, rz = 2650 + 1500, 1600, 1600, 1500
    return math.ceil(centre + rz * math.sqrt(1 - (x / rx) ** 2 - (y / ry) ** 2))


def test_perch_heights_are_derived_from_the_part_under_each_point():
    kinds = world_object_catalog().by_key()
    tree = [perch.position_mm for perch in kinds["planter_tree"].perches]
    assert tree == [(x, y, _crown_top(x, y)) for x, y, _ in tree]
    assert tree[0] == (0, 0, 5650)
    assert kinds["lamp_post"].perches[0].position_mm == (1275, 0, 5800)
    assert [host.count for host in kinds["planter_tree"].hosts] == [3]
    assert all(
        not kind.perches and not kind.hosts
        for key, kind in kinds.items()
        if key not in ("planter_tree", "lamp_post")
    )


def _load(tmp_path: Path, change) -> Any:
    shutil.copy(_V2, tmp_path / _V2.name)
    shutil.copy(CATALOG_DIRECTORY / "world-object.v1.json", tmp_path / "world-object.v1.json")
    document = json.loads(_V3.read_text(encoding="utf-8"))
    entries = {entry["key"]: entry for entry in document["entries"]}
    change(entries)
    (tmp_path / _V3.name).write_text(json.dumps(document), encoding="utf-8")
    return load_world_object_catalog(tmp_path)


def test_the_published_file_loads_through_the_path_its_refusals_take(tmp_path):
    assert _load(tmp_path, lambda entries: None).sha256 == world_object_catalog().sha256


def _perch(x: int, y: int, span: int = 300) -> dict[str, Any]:
    return {"x_mm": x, "y_mm": y, "span_mm": span, "source": "declared/perches"}


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (
            lambda e: e["lamp_post"]["perches"].append(_perch(0, 0)),
            "is not a box or an ellipsoid",
        ),
        (
            lambda e: e["lamp_post"]["perches"].append(_perch(5000, 0)),
            "no part lies under the perch",
        ),
        (
            lambda e: e["planter_tree"]["perches"].append(_perch(0, 100, 600)),
            "closer than half their spans",
        ),
        (
            lambda e: e["marker_cube"]["perches"].append(_perch(0, 0)),
            "a marker has no parts to perch on",
        ),
        (
            lambda e: e["lamp_post"]["perches"][0].update(source="declared/nowhere"),
            "cites declared/nowhere, which it does not declare",
        ),
        (
            lambda e: e["planter_tree"]["hosts"].append(dict(e["planter_tree"]["hosts"][0])),
            "names one flight kind twice",
        ),
        (lambda e: e["planter_tree"]["hosts"][0].update(count=0), "count is an int in"),
    ],
    ids=[
        "on_the_lamp_pole_a_prism",
        "over_nothing",
        "too_close_to_another",
        "on_a_marker",
        "undeclared_source",
        "kind_hosted_twice",
        "no_flyers_hosted",
    ],
)
def test_the_loader_refuses_a_perch_or_a_host_by_name(tmp_path, change, match):
    with pytest.raises(CatalogError, match=match):
        _load(tmp_path, change)
