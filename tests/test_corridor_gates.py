"""The corridor's mechanical gates, measured from its generated records, and shown able to fail.

``exulanica/grammar/grammars/city/generation/gates.py`` counts each gate from records. The corridor
city passes every one, and the corridor tile's owned records pass every one on their own. Each
gate is then broken by one change to the records, and only that gate fails, so no gate passes
because it cannot see anything.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import pytest
from exulanica.canonical import canonical_json
from exulanica.errors import CanonicalisationError
from exulanica.grammar.grammars.city.facade import BayLayout, FacadeRecord
from exulanica.grammar.grammars.city.generation.corridor import CORRIDOR_TILE
from exulanica.grammar.grammars.city.generation.gates import measure_gates
from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.grammar.grammars.city.material import SurfaceMaterialRecord
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord
from exulanica.grammar.grammars.city.streets import CurbEdgeRecord
from exulanica.grammar.records import record_payload

from corridor_city import documents, records

_GATES = (
    "facade_coverage",
    "ground_band",
    "bay_pitch",
    "kerb_height",
    "furniture_outside_footprints",
    "materials_name_texture_sets",
    "section_5_1",
)


def test_the_corridor_city_passes_every_gate():
    report = measure_gates(records())
    assert report.passes() == dict.fromkeys(_GATES, True)
    figures = report.as_dict()
    assert figures["facade_coverage_percent"] == 100
    assert figures["objects_inside_footprints"] == 0
    assert figures["bayable_edges_without_bays"] == 0
    assert 100 * figures["frontage_faces_in_pitch_band"] >= 95 * figures["frontage_faces_with_bays"]


def test_the_corridor_tile_alone_passes_every_gate():
    owned = documents()[CORRIDOR_TILE].grammars[0].owned
    report = measure_gates(owned)
    assert report.buildings >= 14
    assert report.passes() == dict.fromkeys(_GATES, True)


def _first(record_type: type) -> object:
    return next(record for record in records() if type(record) is record_type)


def _replace(old: object, new: object) -> list[object]:
    return [new if record is old else record for record in records()]


def _drop_a_facade() -> list[object]:
    face = _first(FacadeRecord)
    return [record for record in records() if record is not face]


def _band_too_short() -> list[object]:
    face = next(
        record
        for record in records()
        if isinstance(record, FacadeRecord) and record.first_storey == 0
    )
    return _replace(face, dataclasses.replace(face, band_top_mm=3_999))


def _pitches_too_narrow() -> list[object]:
    narrowed = []
    for record in records():
        if isinstance(record, FacadeRecord) and record.exposure == "frontage" and record.bays.count:
            layout = record.bays
            record = dataclasses.replace(record, bays=BayLayout(layout.count, 2_000, 0, 0))
        narrowed.append(record)
    return narrowed


def _kerb_too_low() -> list[object]:
    curb = _first(CurbEdgeRecord)
    return _replace(curb, dataclasses.replace(curb, kerb_height_mm=99))


def _lamp_inside_a_building() -> list[object]:
    lamp = _first(StreetFurnitureRecord)
    building = _first(MassingRecord)
    x, y = building.tiers[0].ring_mm[0]  # type: ignore[attr-defined]
    return _replace(lamp, dataclasses.replace(lamp, x_mm=x + 1_000, y_mm=y + 1_000))


def _material_without_a_set() -> list[object]:
    item = _first(SurfaceMaterialRecord)
    return _replace(item, dataclasses.replace(item, texture_set_id=""))


def _facade_without_a_seed() -> list[object]:
    face = _first(FacadeRecord)
    return _replace(face, dataclasses.replace(face, seed=""))


_BREAKS: dict[str, Callable[[], list[object]]] = {
    "facade_coverage": _drop_a_facade,
    "ground_band": _band_too_short,
    "bay_pitch": _pitches_too_narrow,
    "kerb_height": _kerb_too_low,
    "furniture_outside_footprints": _lamp_inside_a_building,
    "materials_name_texture_sets": _material_without_a_set,
    "section_5_1": _facade_without_a_seed,
}


@pytest.mark.parametrize("gate", _GATES)
def test_each_gate_fails_on_its_own_break(gate):
    passes = measure_gates(_BREAKS[gate]()).passes()
    assert passes == {name: name != gate for name in _GATES}


def test_canonical_json_accepts_the_record_set_and_refuses_one_injected_float():
    payloads = [record_payload(record) for record in documents()[CORRIDOR_TILE].grammars[0].owned]
    assert canonical_json(payloads)
    poisoned = [dict(payload) for payload in payloads]
    poisoned[0] = {**poisoned[0], "fields": {**poisoned[0]["fields"], "injected": 0.5}}
    with pytest.raises(CanonicalisationError):
        canonical_json(poisoned)
