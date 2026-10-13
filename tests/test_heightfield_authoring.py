"""Explicit terrain admission and immutable receipt replay without flat society records."""

import copy
import json

import pytest
from exulanica.world.composers import receipt_sha256, site_plan
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.heightfield_contact import read_heightfield_contact
from exulanica.world.heightfield_geometry import read_heightfield_geometry
from exulanica.world.kinds.worker import compose_terrain_job, drawing_job, place_job
from exulanica.world.site_drawing import site_drawing
from exulanica.world.structure import validate_candidate
from exulanica.world.terrain_authoring import (
    CAPABILITIES,
    PROFILE,
    TerrainAuthoringRefused,
    read_terrain_authoring,
)

from test_heightfield_contact import contact_document
from test_heightfield_geometry import terrain


def authoring():
    geometry = read_heightfield_geometry(
        terrain([0, 1000, 2000], [-2000, -1000, 0], [1000, 1333, 1666] * 3)
    )
    contact = read_heightfield_contact(contact_document(geometry), geometry)
    return {
        "profile": PROFILE,
        "region_id": "region:generated",
        "geometry": geometry.document(),
        "geometry_sha256": geometry.sha256,
        "contact": contact.document(),
        "contact_sha256": contact.sha256,
        "bounds_mm": {"east": [0, 2000], "south": [-2000, 0]},
        "entry": {"position_mm": [1001, -1000], "facing_mm": [1, 0]},
        "capabilities": dict(CAPABILITIES),
    }


def test_exact_entry_receipt_replay_and_explicit_terrain_drawing():
    doc = authoring()
    composed = site_plan.compose_terrain(doc, "world:generated:terrain-test")
    validate_candidate(composed.candidate)
    stored = json.loads(json.dumps(composed.receipt))
    assert receipt_sha256(stored) == composed.receipt_sha256
    assert site_plan.records(stored) == composed.records
    assert stored["arrival"]["contact"]["height_mm"] == {
        "numerator": "1333333",
        "denominator": "1000",
    }
    assert stored["arrival"]["position_mm"] == [1001, 1333, -1000]
    extent = site_plan.stated_extent(composed.candidate.topology, composed.candidate.placement)
    assert extent.arrival_mm == (1001, 1333, -1000)
    drawing = site_drawing(
        world_id=stored["world_id"],
        receipt=stored,
        receipt_sha256=composed.receipt_sha256,
        records=composed.records,
    )
    assert drawing["terrain"]["geometry"] == doc["geometry"]
    assert drawing["arrival"] == stored["arrival"]
    assert drawing["capabilities"] == CAPABILITIES
    assert not {"slots", "kind", "routine", "society", "grammar"} & (drawing.keys() | stored.keys())
    with pytest.raises(InvalidStructuralData, match="terrain_society_projection_unavailable"):
        site_plan.society_place("place:test", stored, composed.records)
    doc["geometry"]["height_mm"][0] = 0
    assert composed.records[0].document()["geometry"]["height_mm"][0] == 1000


@pytest.mark.parametrize(
    "change", ["extra", "digest", "bounds", "capabilities", "outside", "unknown", "obstructed"]
)
def test_admission_refuses_invalid_or_unavailable_stationary_entry(change):
    doc = authoring()
    if change == "extra":
        doc["kind"] = "fake"
    elif change == "digest":
        doc["geometry_sha256"] = "0" * 64
    elif change == "bounds":
        doc["bounds_mm"]["east"] = [-1000, 1000]
    elif change == "capabilities":
        doc["capabilities"]["person_navigation"] = 1
    elif change == "outside":
        doc["entry"]["position_mm"] = [0, 0]
    else:
        obstruction = {"kind": "unknown", "obstruction_id": "obstacle:test"}
        if change == "obstructed":
            obstruction = {
                "kind": "aabb",
                "obstruction_id": "obstacle:test",
                "bounds_mm": [1001, 1334, -1000, 1002, 1400, -999],
            }
        doc["contact"]["obstructions"] = [obstruction]
        doc["contact_sha256"] = read_heightfield_contact(
            doc["contact"], read_heightfield_geometry(doc["geometry"])
        ).sha256
    with pytest.raises(TerrainAuthoringRefused):
        read_terrain_authoring(doc)


def test_worker_cold_replay_and_unavailable_projection_are_named():
    answer = compose_terrain_job(
        "workspace:terrain-test", authoring(), "world:generated:terrain-test"
    )
    assert answer["status"] == "done"
    composed = answer["composed"]
    assert answer["placed"]["code"] == "terrain_society_projection_unavailable"
    cold = drawing_job(
        "workspace:cold", composed.receipt["world_id"], composed.receipt, composed.receipt_sha256
    )
    assert cold["body"] == answer["body"]
    placed = place_job("workspace:cold", composed.receipt, composed.receipt_sha256, "place:test")
    assert placed["status"] == "refused" and "place" not in placed
    tampered = copy.deepcopy(composed.receipt)
    tampered["arrival"]["position_mm"][1] = 0
    with pytest.raises(InvalidStructuralData):
        site_plan.records(tampered)


def test_terrain_worker_cannot_restore_erased_receipt_cache(monkeypatch):
    import exulanica.world.kinds.worker as worker_module

    worker = worker_module.KindWorker()
    monkeypatch.setattr(worker_module, "_worker", worker)
    composer = worker_module.TerrainWorkerComposer("terrain-workspace")
    digest = "a" * 64
    key = worker_module.drawing_key("terrain-workspace", digest)
    composer.drawn = (key, {"body": "late private source"})
    worker.drawings.put(key, {"body": "existing private source"})
    worker.forget_receipts("terrain-workspace", frozenset({digest}))
    composer.keep()
    assert worker.drawings.get(key) is None
    worker.close()
