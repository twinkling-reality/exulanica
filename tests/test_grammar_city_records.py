"""Every city v2 record kind refuses what its shape does not admit, field by field and rule by rule.

The cases are generated from the shapes themselves (``CITY_SHAPES`` and every nested shape they
use) and applied to real records from the hand-written fixture, so a field added to a shape is
tested the moment it exists, and a shape nobody can instantiate from the fixture fails here.

*   **Missing and extra fields** are refused by :func:`exulanica.grammar.shapes.read_record` at
    every depth.
*   **Wrong types.** A float in any field raises ``CanonicalisationError`` from canonical JSON
    before any field check runs; ``bool``, ``None`` and a list are refused as values no record
    holds; a string where an integer belongs, and an integer where a string belongs, are refused
    by the field check.
*   **Out of range.** Every declared integer bound refuses the value one past it, and every
    declared count refuses one item too few or too many.
*   **Named rules.** Every rule of every shape has at least one case below in which every field
    is valid, that rule refuses the record, and every other rule of the shape accepts it. A test
    holds the case table to the full list of rule names, so a new rule without a case fails.
*   **The target architecture's bounds** are pinned by number, not read back from the shapes:
    kerb 100 to 180 mm, vitrine depth 600 to 1500 mm, ground band 4000 to 6000 mm, reveal 120 to
    250 mm, string course 60 to 200 mm, cornice 400 to 900 mm, and bay pitch 2400 to 3500 mm as a
    declared parameter.
"""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from exulanica.errors import CanonicalisationError
from exulanica.grammar import shapes
from exulanica.grammar.contract import DeclaredSemantics
from exulanica.grammar.errors import (
    GrammarError,
    InvalidParameterError,
    InvalidRecordError,
    InvalidSeedError,
)
from exulanica.grammar.geometry import Extent
from exulanica.grammar.grammars.city import CITY_SHAPES
from exulanica.grammar.grammars.city.common import FormPart
from exulanica.grammar.grammars.city.descriptor import CITY_SURFACE
from exulanica.grammar.grammars.city.facade import (
    Awning,
    BayLayout,
    GroundPanel,
    Moulding,
)
from exulanica.grammar.grammars.city.roads import SignalGroup, Stripe
from exulanica.grammar.grammars.city.tile import GrammarPin
from exulanica.grammar.parameters import ParameterBinding, require_parameter_bindings
from exulanica.grammar.records import record_payload

from city_v2_fixture import builder, records_by_kind

FIXTURE = builder()
_BY_KIND = {**records_by_kind(), "city.tile": [FIXTURE.tile]}


def _nested_shapes() -> dict[str, shapes.RecordShape]:
    found: dict[str, shapes.RecordShape] = {}

    def visit(shape: shapes.RecordShape) -> None:
        for field_shape in shape.fields:
            if field_shape.shape is not None and field_shape.shape.name not in found:
                found[field_shape.shape.name] = field_shape.shape
                visit(field_shape.shape)

    for shape in CITY_SHAPES:
        visit(shape)
    return found


_NESTED = _nested_shapes()
_SHAPES: dict[str, shapes.RecordShape] = {
    **{shape.name: shape for shape in CITY_SHAPES},
    **_NESTED,
}


def _instances(value: object, shape: shapes.RecordShape) -> Iterator[tuple[str, object]]:
    """Every (shape name, instance) inside a record, the record itself first."""
    yield shape.name, value
    for field_shape in shape.fields:
        if field_shape.shape is None:
            continue
        inner = getattr(value, field_shape.name)
        for item in inner if field_shape.kind == "records" else (inner,):
            yield from _instances(item, field_shape.shape)


def _samples() -> dict[str, object]:
    samples: dict[str, object] = {}
    for shape in CITY_SHAPES:
        for record in _BY_KIND.get(shape.kind, []):
            for name, instance in _instances(record, shape):
                samples.setdefault(name, instance)
    return samples


_SAMPLES = _samples()


def test_the_fixture_instantiates_every_record_shape_and_every_nested_shape():
    assert len(CITY_SHAPES) == 27
    assert set(_SAMPLES) == set(_SHAPES), sorted(set(_SHAPES) ^ set(_SAMPLES))
    for name, sample in _SAMPLES.items():
        shapes.validate_record(sample, _SHAPES[name])


def _field_cases(predicate: Callable[[shapes.FieldShape], bool] = lambda _field: True):
    return [
        pytest.param(name, field_shape.name, id=f"{name}.{field_shape.name}")
        for name, shape in sorted(_SHAPES.items())
        for field_shape in shape.fields
        if predicate(field_shape)
    ]


def _payload_fields(name: str) -> tuple[dict[str, Any], Callable[[dict[str, Any]], object]]:
    """The sample's payload fields, and how to wrap changed fields back into a payload."""
    payload = record_payload(_SAMPLES[name])
    if _SHAPES[name].kind:
        return dict(payload["fields"]), lambda fields: {**payload, "fields": fields}
    return dict(payload), lambda fields: fields


# -------------------------------------------------------------------------------------------
# Reading a payload back


@pytest.mark.parametrize("name", sorted(_SHAPES))
def test_every_sample_reads_back_from_its_payload_unchanged(name):
    sample = _SAMPLES[name]
    assert shapes.read_record(record_payload(sample), _SHAPES[name]) == sample


@pytest.mark.parametrize("name,field", _field_cases())
def test_a_payload_missing_a_field_is_refused(name, field):
    fields, wrap = _payload_fields(name)
    del fields[field]
    with pytest.raises(InvalidRecordError, match=rf"missing fields \['{field}'\]"):
        shapes.read_record(wrap(fields), _SHAPES[name])


@pytest.mark.parametrize("name", sorted(_SHAPES))
def test_a_payload_with_an_extra_field_is_refused(name):
    fields, wrap = _payload_fields(name)
    fields["unexpected_mm"] = 1
    with pytest.raises(InvalidRecordError, match=r"unknown fields \['unexpected_mm'\]"):
        shapes.read_record(wrap(fields), _SHAPES[name])


def test_a_payload_is_refused_under_another_kind_or_version():
    payload = record_payload(_SAMPLES["city.street_node"])
    with pytest.raises(InvalidRecordError, match=r"is a city\.street_node"):
        shapes.read_record({**payload, "kind": "city.block"}, _SHAPES["city.street_node"])
    with pytest.raises(InvalidRecordError, match="is version 2"):
        shapes.read_record({**payload, "version": 1}, _SHAPES["city.street_node"])


def test_a_nested_payload_missing_a_field_is_refused_from_the_top():
    payload = record_payload(_SAMPLES["city.street_node"])
    extent = dict(payload["fields"]["extent"])
    del extent["max_z_mm"]
    broken = {**payload, "fields": {**payload["fields"], "extent": extent}}
    with pytest.raises(InvalidRecordError, match=r"extent: unknown fields \[\], missing"):
        shapes.read_record(broken, _SHAPES["city.street_node"])


# -------------------------------------------------------------------------------------------
# Wrong types

_STRING_KINDS = frozenset({"key", "choice", "text", "identity", "hex64", "seed", "texture_set_id"})
_SEQUENCE_KINDS = frozenset(
    {"integers", "keys", "choices", "identities", "texts", "points", "ring", "rings", "records"}
)


def _replace(record: object, **changes: object) -> Any:
    """A copy of ``record`` with ``changes``, set past any ``__post_init__``.

    A record class that checks itself when constructed would otherwise refuse a bad value before
    the shape's validator saw it, and the validator is what these tests hold.
    """
    copied = copy.copy(record)
    for name, value in changes.items():
        object.__setattr__(copied, name, value)
    return copied


@pytest.mark.parametrize("name,field", _field_cases())
def test_a_float_in_any_field_is_refused_by_canonical_json(name, field):
    with pytest.raises(CanonicalisationError):
        shapes.validate_record(_replace(_SAMPLES[name], **{field: 0.5}), _SHAPES[name])


@pytest.mark.parametrize("name,field", _field_cases())
@pytest.mark.parametrize("value", [True, False, None, [1]], ids=["true", "false", "none", "list"])
def test_a_bool_none_or_list_in_any_field_is_refused(name, field, value):
    with pytest.raises(InvalidRecordError):
        shapes.validate_record(_replace(_SAMPLES[name], **{field: value}), _SHAPES[name])


@pytest.mark.parametrize("name,field", _field_cases(lambda field: field.kind == "integer"))
def test_a_string_where_an_integer_belongs_is_refused(name, field):
    with pytest.raises(InvalidRecordError, match="is an int"):
        shapes.validate_record(_replace(_SAMPLES[name], **{field: "1"}), _SHAPES[name])


@pytest.mark.parametrize("name,field", _field_cases(lambda field: field.kind in _STRING_KINDS))
def test_an_integer_where_a_string_belongs_is_refused(name, field):
    expected = InvalidSeedError if _SHAPES[name].field(field).kind == "seed" else InvalidRecordError
    with pytest.raises(expected):
        shapes.validate_record(_replace(_SAMPLES[name], **{field: 1}), _SHAPES[name])


@pytest.mark.parametrize("name,field", _field_cases(lambda field: field.kind in _SEQUENCE_KINDS))
def test_a_bare_value_where_a_sequence_belongs_is_refused(name, field):
    with pytest.raises(InvalidRecordError):
        shapes.validate_record(_replace(_SAMPLES[name], **{field: 1}), _SHAPES[name])


@pytest.mark.parametrize("name,field", _field_cases(lambda field: field.kind == "record"))
def test_another_record_where_a_nested_record_belongs_is_refused(name, field):
    other = Extent(0, 0, 0, 0, 0, 0)
    if _SHAPES[name].field(field).shape is shapes.EXTENT_SHAPE:
        other = BayLayout(0, 0, 0, 0)
    with pytest.raises(InvalidRecordError, match=f"is a {_SHAPES[name].field(field).shape.name}"):
        shapes.validate_record(_replace(_SAMPLES[name], **{field: other}), _SHAPES[name])


# -------------------------------------------------------------------------------------------
# Out of range


@pytest.mark.parametrize(
    "name,field",
    _field_cases(lambda field: field.kind in ("integer", "integers") and field.minimum is not None),
)
def test_one_below_a_declared_minimum_is_refused(name, field):
    shape = _SHAPES[name]
    field_shape = shape.field(field)
    low = field_shape.minimum - 1
    value = low if field_shape.kind == "integer" else (low, *getattr(_SAMPLES[name], field)[1:])
    with pytest.raises(InvalidRecordError, match=f"below its minimum {field_shape.minimum}"):
        shapes.validate_record(_replace(_SAMPLES[name], **{field: value}), shape)


@pytest.mark.parametrize(
    "name,field",
    _field_cases(lambda field: field.kind in ("integer", "integers") and field.maximum is not None),
)
def test_one_above_a_declared_maximum_is_refused(name, field):
    shape = _SHAPES[name]
    field_shape = shape.field(field)
    high = field_shape.maximum + 1
    value = high if field_shape.kind == "integer" else (*getattr(_SAMPLES[name], field)[:-1], high)
    with pytest.raises(InvalidRecordError, match=f"above its maximum {field_shape.maximum}"):
        shapes.validate_record(_replace(_SAMPLES[name], **{field: value}), shape)


@pytest.mark.parametrize(
    "name,field",
    _field_cases(lambda field: field.kind in _SEQUENCE_KINDS - {"ring"} and field.count_minimum),
)
def test_one_item_fewer_than_a_declared_count_is_refused(name, field):
    shape = _SHAPES[name]
    minimum = shape.field(field).count_minimum
    value = getattr(_SAMPLES[name], field)[: minimum - 1]
    with pytest.raises(InvalidRecordError, match=f"holds at least {minimum}"):
        shapes.validate_record(_replace(_SAMPLES[name], **{field: value}), shape)


def _grown(value: tuple[Any, ...]) -> tuple[Any, ...]:
    """``value`` one item longer. The count is checked before any item is."""
    return (*value, value[-1] if value else 0)


@pytest.mark.parametrize(
    "name,field",
    _field_cases(
        lambda field: field.kind in _SEQUENCE_KINDS - {"ring"} and field.count_maximum is not None
    ),
)
def test_one_item_more_than_a_declared_count_is_refused(name, field):
    shape = _SHAPES[name]
    field_shape = shape.field(field)
    value = getattr(_SAMPLES[name], field)
    while len(value) <= field_shape.count_maximum:
        value = _grown(value)
    with pytest.raises(InvalidRecordError, match=f"holds at most {field_shape.count_maximum}"):
        shapes.validate_record(_replace(_SAMPLES[name], **{field: value}), shape)


@pytest.mark.parametrize(
    "name,field",
    _field_cases(lambda field: field.kind == "ring" and field.count_maximum is not None),
)
def test_a_ring_with_a_vertex_more_than_declared_is_refused(name, field):
    shape = _SHAPES[name]
    ring = getattr(_SAMPLES[name], field)
    (x0, y0), (x1, y1) = ring[0], ring[1]
    grown = (ring[0], ((x0 + x1) // 2, (y0 + y1) // 2 - 1), *ring[1:])
    with pytest.raises(InvalidRecordError, match="vertices"):
        shapes.validate_record(_replace(_SAMPLES[name], **{field: grown}), shape)


def test_a_repeated_identity_key_or_choice_in_a_sequence_is_refused():
    premises = _BY_KIND["city.premises"][0]
    doubled = (premises.entrance_identities[0],) * 2
    with pytest.raises(InvalidRecordError, match="repeats an item"):
        shapes.validate_record(
            _replace(premises, entrance_identities=doubled), _SHAPES["city.premises"]
        )
    lane = _BY_KIND["city.lane"][2]
    with pytest.raises(InvalidRecordError, match="repeats an item"):
        shapes.validate_record(_replace(lane, turns=("left", "left")), _SHAPES["city.lane"])
    with pytest.raises(InvalidRecordError, match="in the order"):
        shapes.validate_record(_replace(lane, turns=("straight", "left")), _SHAPES["city.lane"])


# -------------------------------------------------------------------------------------------
# The target architecture's bounds, by number


def _field_bounds(kind: str, field: str) -> tuple[int | None, int | None]:
    field_shape = _SHAPES[kind].field(field)
    return field_shape.minimum, field_shape.maximum


def _accepts(name: str, record: object) -> bool:
    try:
        shapes.validate_record(record, _SHAPES[name])
    except (GrammarError, CanonicalisationError):
        return False
    return True


def test_kerb_height_is_100_to_180_mm_on_every_curb():
    assert _field_bounds("city.curb_edge", "kerb_height_mm") == (100, 180)
    curb = _BY_KIND["city.curb_edge"][0]
    for height, admitted in ((99, False), (100, True), (180, True), (181, False)):
        assert _accepts("city.curb_edge", _replace(curb, kerb_height_mm=height)) is admitted


def test_a_vitrine_is_600_to_1500_mm_deep():
    assert _field_bounds("city.vitrine", "depth_mm") == (600, 1_500)
    vitrine = _BY_KIND["city.vitrine"][0]
    for depth, admitted in ((599, False), (600, True), (1_500, True), (1_501, False)):
        assert _accepts("city.vitrine", _replace(vitrine, depth_mm=depth)) is admitted


def test_the_ground_band_is_4000_to_6000_mm():
    assert _field_bounds("city.massing", "ground_storey_height_mm") == (4_000, 6_000)
    facade = FIXTURE.facades[0]
    assert facade.first_storey == 0
    for top, admitted in ((3_999, False), (4_000, True), (6_000, True), (6_001, False)):
        assert _accepts("city.facade", _replace(facade, band_top_mm=top)) is admitted


def test_a_reveal_is_120_to_250_mm():
    assert _field_bounds("OpeningGrid", "reveal_depth_mm") == (120, 250)
    grid = FIXTURE.facades[0].openings[0]
    for depth, admitted in ((119, False), (120, True), (250, True), (251, False)):
        assert _accepts("OpeningGrid", _replace(grid, reveal_depth_mm=depth)) is admitted


def test_a_string_course_is_60_to_200_mm_tall():
    facade = FIXTURE.facades[0]
    first, *rest = facade.string_courses
    for height, admitted in ((59, False), (60, True), (200, True), (201, False)):
        course = _replace(first, z_top_mm=first.z_bottom_mm + height)
        record = _replace(facade, string_courses=(course, *rest))
        assert _accepts("city.facade", record) is admitted, height


def test_a_cornice_is_400_to_900_mm_tall_in_total():
    facade = FIXTURE.facades[0]
    *lower, top = facade.cornice
    base = facade.cornice[0].z_bottom_mm
    for height, admitted in ((399, False), (400, True), (900, True), (901, False)):
        record = _replace(facade, cornice=(*lower, _replace(top, z_top_mm=base + height)))
        assert _accepts("city.facade", record) is admitted, height


def test_bay_pitch_is_a_face_parameter_of_2400_to_3500_mm():
    spec = CITY_SURFACE.parameters.get("bay_pitch_mm")
    assert (spec.kind, spec.unit, spec.level, spec.stage) == ("integer", "mm", "face", "facade")
    assert (spec.minimum, spec.maximum) == (2_400, 3_500)
    facade = FIXTURE.facades[0]
    for pitch, admitted in ((2_399, False), (2_400, True), (3_500, True), (3_501, False)):
        bindings = tuple(
            ParameterBinding(binding.name, pitch, binding.source)
            if binding.name == "bay_pitch_mm"
            else binding
            for binding in facade.parameters
        )
        try:
            require_parameter_bindings(
                "parameters",
                bindings,
                CITY_SURFACE.parameters,
                CITY_SURFACE.cascade,
                stage="facade",
            )
        except InvalidParameterError:
            assert not admitted, pitch
        else:
            assert admitted, pitch


# -------------------------------------------------------------------------------------------
# Named rules

_OTHER_IDENTITY = "00000000-0000-5000-8000-000000000000"


@dataclasses.dataclass(frozen=True)
class RuleCase:
    rule: str
    shape: str
    what: str
    make: Callable[[], object]
    #: False only where a field check guards the rule, so the rule is shown to refuse on its own.
    fields_valid: bool = True


def _plane_recorded() -> DeclaredSemantics:
    return _replace(DeclaredSemantics("facade", ()), plane="recorded")


def _shifted(extent: Extent, **changes: int) -> Extent:
    return _replace(extent, **changes)


def _cases() -> list[RuleCase]:
    node = FIXTURE.nodes[0]
    segment = FIXTURE.segments[0]
    block = FIXTURE.block
    curb = FIXTURE.curbs[0]
    crossing = FIXTURE.crossings[0]
    parking_lane, backward, forward = FIXTURE.lanes[:3]
    connection = FIXTURE.connections[0]
    signal = FIXTURE.signal
    bay_space = FIXTURE.parking[0]
    cycle_space = FIXTURE.parking[2]
    marking = FIXTURE.markings[0]
    parcel = FIXTURE.parcels[1]
    building = FIXTURE.building
    tier = building.tiers[0]
    rooftop = FIXTURE.rooftops[0]
    south, chamfer, _east, _rear, party = FIXTURE.facades[:5]
    shop_bay = FIXTURE.south_bays[0]
    door = FIXTURE.shop_door
    material = FIXTURE.materials[0]
    furniture = FIXTURE.furniture[0]
    tree = FIXTURE.trees[0]
    shop, _books, flats = FIXTURE.premises
    terrain = FIXTURE.terrain
    district = FIXTURE.district
    tile = FIXTURE.tile
    pin = tile.grammar_versions[0]
    return [
        RuleCase(
            "extent_corners_ordered",
            "Extent",
            "min x above max x",
            lambda: Extent(1, 0, 0, 0, 0, 0),
        ),
        RuleCase(
            "semantics_plane_invented",
            "DeclaredSemantics",
            "a plane other than invented",
            _plane_recorded,
            fields_valid=False,
        ),
        RuleCase(
            "form_part_counts",
            "FormPart",
            "a box with eight segments",
            lambda: FormPart("box", "object_primary", 0, 0, 0, 10, 10, 10, 1_000_000, 8, 1),
        ),
        RuleCase(
            "form_part_counts",
            "FormPart",
            "a prism with a segment count that is not a power of two",
            lambda: FormPart("prism", "object_primary", 0, 0, 0, 10, 10, 10, 1_000_000, 6, 1),
        ),
        RuleCase(
            "form_part_counts",
            "FormPart",
            "a tapered ellipsoid",
            lambda: FormPart("ellipsoid", "object_primary", 0, 0, 0, 10, 10, 10, 500_000, 8, 4),
        ),
        RuleCase(
            "terrain_grid_matches_tile",
            "city.terrain",
            "a tile ordinal that is not its coordinates'",
            lambda: _replace(terrain, tile_ordinal=1),
        ),
        RuleCase(
            "terrain_grid_matches_tile",
            "city.terrain",
            "a cell that does not divide the tile",
            lambda: _replace(terrain, cell_mm=7_000),
        ),
        RuleCase(
            "terrain_slope_exact",
            "city.terrain",
            "a slope the heights do not give",
            lambda: _replace(terrain, slope_millionths=(1, *terrain.slope_millionths[1:])),
        ),
        RuleCase(
            "terrain_extent_is_tile",
            "city.terrain",
            "an extent taller than the heights",
            lambda: _replace(terrain, extent=_shifted(terrain.extent, max_z_mm=1)),
        ),
        RuleCase(
            "district_boundary_in_extent",
            "city.district",
            "a boundary past its extent",
            lambda: _replace(district, extent=_shifted(district.extent, max_x_mm=100_000)),
        ),
        RuleCase(
            "node_extent_is_point",
            "city.street_node",
            "an extent wider than the point",
            lambda: _replace(node, extent=_shifted(node.extent, max_x_mm=node.x_mm + 1)),
        ),
        RuleCase(
            "segment_geometry",
            "city.street_segment",
            "a segment from a node to itself",
            lambda: _replace(segment, end_node_identity=segment.start_node_identity),
        ),
        RuleCase(
            "segment_geometry",
            "city.street_segment",
            "a length that is not the centreline's",
            lambda: _replace(segment, length_mm=segment.length_mm - 1),
        ),
        RuleCase(
            "segment_geometry",
            "city.street_segment",
            "a centreline past its extent",
            lambda: _replace(segment, extent=_shifted(segment.extent, max_z_mm=-1)),
        ),
        RuleCase(
            "block_geometry",
            "city.block",
            "a centroid that is not the ring's",
            lambda: _replace(block, centroid_x_mm=block.centroid_x_mm + 1),
        ),
        RuleCase(
            "block_geometry",
            "city.block",
            "a boundary past its extent",
            lambda: _replace(block, extent=_shifted(block.extent, min_x_mm=20_001)),
        ),
        RuleCase(
            "curb_geometry",
            "city.curb_edge",
            "a corner radius with no next curb",
            lambda: _replace(curb, next_curb_identity=()),
        ),
        RuleCase(
            "curb_geometry",
            "city.curb_edge",
            "a curb that follows itself",
            lambda: _replace(curb, next_curb_identity=(curb.identity,)),
        ),
        RuleCase(
            "curb_geometry",
            "city.curb_edge",
            "a kerb line past its extent",
            lambda: _replace(curb, extent=_shifted(curb.extent, min_z_mm=-94)),
        ),
        RuleCase(
            "crossing_geometry",
            "city.crossing",
            "a crossing line past its extent",
            lambda: _replace(crossing, extent=_shifted(crossing.extent, max_y_mm=44_749)),
        ),
        RuleCase(
            "lane_direction_and_turns",
            "city.lane",
            "a backward lane that runs with the segment",
            lambda: _replace(backward, start_offset_mm=0, end_offset_mm=36_750),
        ),
        RuleCase(
            "lane_direction_and_turns",
            "city.lane",
            "a forward lane that runs against the segment",
            lambda: _replace(forward, start_offset_mm=26_000, end_offset_mm=0),
        ),
        RuleCase(
            "lane_direction_and_turns",
            "city.lane",
            "a lane with traffic and no turns",
            lambda: _replace(forward, turns=()),
        ),
        RuleCase(
            "lane_direction_and_turns",
            "city.lane",
            "a lane without traffic that lists turns",
            lambda: _replace(parking_lane, turns=("straight",)),
        ),
        RuleCase(
            "lane_direction_and_turns",
            "city.lane",
            "a centreline past its extent",
            lambda: _replace(forward, extent=_shifted(forward.extent, max_x_mm=45_999)),
        ),
        RuleCase(
            "connection_path",
            "city.lane_connection",
            "a connection from a lane to itself",
            lambda: _replace(connection, to_lane_identity=connection.from_lane_identity),
        ),
        RuleCase(
            "connection_path",
            "city.lane_connection",
            "a path past its extent",
            lambda: _replace(connection, extent=_shifted(connection.extent, min_x_mm=46_001)),
        ),
        RuleCase(
            "signal_group_not_empty",
            "SignalGroup",
            "a group that releases nothing",
            lambda: SignalGroup("phase_c", (), ()),
        ),
        RuleCase(
            "signal_groups_distinct",
            "city.signal",
            "a group named twice",
            lambda: _replace(
                signal,
                groups=(
                    signal.groups[0],
                    _replace(signal.groups[1], group=signal.groups[0].group),
                    *signal.groups[2:],
                ),
            ),
        ),
        RuleCase(
            "signal_groups_distinct",
            "city.signal",
            "a movement in two groups",
            lambda: _replace(
                signal,
                groups=(
                    signal.groups[0],
                    _replace(
                        signal.groups[1],
                        connection_identities=(
                            *signal.groups[1].connection_identities,
                            signal.groups[0].connection_identities[0],
                        ),
                    ),
                    *signal.groups[2:],
                ),
            ),
        ),
        RuleCase(
            "parking_placement",
            "city.parking_space",
            "an access stretch that ends where it starts",
            lambda: _replace(bay_space, access_end_mm=bay_space.access_start_mm),
        ),
        RuleCase(
            "parking_placement",
            "city.parking_space",
            "a carriageway bay that lists stands",
            lambda: _replace(bay_space, furniture_identities=(_OTHER_IDENTITY,)),
        ),
        RuleCase(
            "parking_placement",
            "city.parking_space",
            "a carriageway bay for two vehicles",
            lambda: _replace(bay_space, capacity=2),
        ),
        RuleCase(
            "parking_placement",
            "city.parking_space",
            "a footway space in a lane",
            lambda: _replace(cycle_space, lane_identity=(_OTHER_IDENTITY,)),
        ),
        RuleCase(
            "parking_placement",
            "city.parking_space",
            "a footway space with no stands",
            lambda: _replace(cycle_space, furniture_identities=()),
        ),
        RuleCase(
            "parking_placement",
            "city.parking_space",
            "a footprint past its extent",
            lambda: _replace(bay_space, extent=_shifted(bay_space.extent, max_x_mm=35_999)),
        ),
        RuleCase(
            "stripe_is_a_plan_quad",
            "Stripe",
            "corners turning clockwise",
            lambda: Stripe(tuple(reversed(marking.stripes[0].corners))),
        ),
        RuleCase(
            "marking_in_extent",
            "city.road_marking",
            "a stripe past its extent",
            lambda: _replace(marking, extent=_shifted(marking.extent, max_x_mm=32_999)),
        ),
        RuleCase(
            "parcel_geometry",
            "city.parcel",
            "a centroid that is not the ring's",
            lambda: _replace(parcel, centroid_y_mm=parcel.centroid_y_mm + 1),
        ),
        RuleCase(
            "parcel_geometry",
            "city.parcel",
            "a frontage edge named twice",
            lambda: _replace(
                parcel,
                frontages=(parcel.frontages[0], parcel.frontages[0]),
                frontage_mm=2 * parcel.frontages[0].run_length_mm,
            ),
        ),
        RuleCase(
            "parcel_geometry",
            "city.parcel",
            "a frontage edge the ring does not have",
            lambda: _replace(
                parcel,
                frontages=(parcel.frontages[0], _replace(parcel.frontages[1], edge_ordinal=4)),
            ),
        ),
        RuleCase(
            "parcel_geometry",
            "city.parcel",
            "a frontage run that is not its edge's",
            lambda: _replace(
                parcel,
                frontages=(
                    _replace(parcel.frontages[0], run_length_mm=11_999),
                    parcel.frontages[1],
                ),
                frontage_mm=parcel.frontage_mm - 1,
            ),
        ),
        RuleCase(
            "parcel_geometry",
            "city.parcel",
            "a frontage total that is not the sum",
            lambda: _replace(parcel, frontage_mm=parcel.frontage_mm + 1),
        ),
        RuleCase(
            "parcel_geometry",
            "city.parcel",
            "a threshold past the primary frontage",
            lambda: _replace(parcel, threshold_offset_mm=12_001),
        ),
        RuleCase(
            "parcel_geometry",
            "city.parcel",
            "a boundary past its extent",
            lambda: _replace(parcel, extent=_shifted(parcel.extent, max_y_mm=66_949)),
        ),
        RuleCase(
            "tier_storeys_and_wells",
            "Tier",
            "a tier whose first storey is above its last",
            lambda: _replace(tier, first_storey=3, last_storey=2),
        ),
        RuleCase(
            "tier_storeys_and_wells",
            "Tier",
            "a light well touching its tier",
            lambda: _replace(
                tier,
                light_wells_mm=(
                    ((41_050, 60_050), (43_950, 60_050), (43_950, 62_050), (41_050, 62_050)),
                ),
            ),
        ),
        RuleCase(
            "tier_storeys_and_wells",
            "Tier",
            "two light wells that meet",
            lambda: _replace(
                tier,
                light_wells_mm=(
                    tier.light_wells_mm[0],
                    ((43_000, 61_000), (45_000, 61_000), (45_000, 62_500), (43_000, 62_500)),
                ),
            ),
        ),
        RuleCase(
            "massing_tiers_and_roof",
            "city.massing",
            "a first tier that does not start on storey 0",
            lambda: _replace(building, tiers=(_replace(tier, first_storey=1), building.tiers[1])),
        ),
        RuleCase(
            "massing_tiers_and_roof",
            "city.massing",
            "an upper tier wider than the tier below",
            lambda: _replace(
                building,
                tiers=(
                    tier,
                    _replace(
                        building.tiers[1],
                        ring_mm=(
                            (41_050, 50_950),
                            (54_050, 50_950),
                            (54_050, 62_950),
                            (41_050, 62_950),
                        ),
                    ),
                ),
            ),
        ),
        RuleCase(
            "massing_tiers_and_roof",
            "city.massing",
            "tiers that miss a storey",
            lambda: _replace(building, storeys=5),
        ),
        RuleCase(
            "massing_tiers_and_roof",
            "city.massing",
            "a flat roof with a rise",
            lambda: _replace(building, roof_rise_mm=500),
        ),
        RuleCase(
            "massing_tiers_and_roof",
            "city.massing",
            "a ridge roof with no ridge points",
            lambda: _replace(building, roof_form="ridge", roof_rise_mm=500),
        ),
        RuleCase(
            "massing_tiers_and_roof",
            "city.massing",
            "a ridge that does not join opposite midpoints",
            lambda: _replace(
                building,
                roof_form="ridge",
                roof_rise_mm=500,
                ridge_mm=((47_050, 50_950), (53_050, 56_950)),
            ),
        ),
        RuleCase(
            "massing_tiers_and_roof",
            "city.massing",
            "a ridge roof on a five-sided top tier",
            lambda: _replace(
                building,
                tiers=(_replace(tier, last_storey=3),),
                roof_form="ridge",
                roof_rise_mm=500,
                ridge_mm=((47_050, 48_950), (47_050, 62_950)),
            ),
        ),
        RuleCase(
            "massing_tiers_and_roof",
            "city.massing",
            "a footprint past the extent",
            lambda: _replace(building, extent=_shifted(building.extent, max_x_mm=53_049)),
        ),
        RuleCase(
            "massing_tiers_and_roof",
            "city.massing",
            "an extent below the parapet top",
            lambda: _replace(building, extent=_shifted(building.extent, max_z_mm=15_284)),
        ),
        RuleCase(
            "rooftop_object_placed",
            "city.rooftop_object",
            "a direction of zero length",
            lambda: _replace(rooftop, facing_dx_mm=0, facing_dy_mm=0),
        ),
        RuleCase(
            "rooftop_object_placed",
            "city.rooftop_object",
            "a base past its extent",
            lambda: _replace(rooftop, extent=_shifted(rooftop.extent, min_z_mm=rooftop.z_mm + 1)),
        ),
        RuleCase(
            "bay_count_and_pitch",
            "BayLayout",
            "bays with no pitch",
            lambda: BayLayout(1, 0, 0, 0),
        ),
        RuleCase(
            "bay_count_and_pitch",
            "BayLayout",
            "a pitch with no bays",
            lambda: BayLayout(0, 2_800, 0, 0),
        ),
        RuleCase(
            "opening_head_rise",
            "OpeningGrid",
            "an arch rising more than half the width",
            lambda: _replace(south.openings[0], head_rise_mm=601),
        ),
        RuleCase(
            "moulding_bottom_below_top",
            "Moulding",
            "a moulding of no height",
            lambda: Moulding(4_500, 4_500, 60),
        ),
        *_facade_cases(south, chamfer, party),
        RuleCase(
            "panel_positive",
            "GroundPanel",
            "a panel of no width",
            lambda: GroundPanel("glazing", 600, 600, 600, 3_200, 0),
        ),
        RuleCase(
            "panel_positive",
            "GroundPanel",
            "a panel of no height",
            lambda: GroundPanel("glazing", 0, 600, 600, 600, 0),
        ),
        RuleCase(
            "awning_profile",
            "Awning",
            "an awning that rises to its front edge",
            lambda: Awning(2_900, 3_650, 1_200, 250),
        ),
        RuleCase(
            "awning_profile",
            "Awning",
            "a valance below the base",
            lambda: Awning(700, 500, 1_200, 501),
        ),
        *_bay_cases(shop_bay),
        RuleCase(
            "entrance_placed",
            "city.entrance",
            "an entrance that starts before the face",
            lambda: _replace(door, u_centre_mm=849),
        ),
        RuleCase(
            "entrance_placed",
            "city.entrance",
            "a threshold past its extent",
            lambda: _replace(door, extent=_shifted(door.extent, min_z_mm=door.threshold_z_mm + 1)),
        ),
        RuleCase(
            "material_role_owner",
            "city.surface_material",
            "a building that owns a fascia",
            lambda: _replace(material, surface_kind="city.massing", role="fascia"),
        ),
        RuleCase(
            "furniture_placed",
            "city.street_furniture",
            "a direction of zero length",
            lambda: _replace(furniture, facing_dx_mm=0, facing_dy_mm=0),
        ),
        RuleCase(
            "furniture_placed",
            "city.street_furniture",
            "a base past its extent",
            lambda: _replace(furniture, x_mm=furniture.extent.max_x_mm + 1),
        ),
        RuleCase(
            "tree_placed",
            "city.street_tree",
            "a trunk outside its pit",
            lambda: _replace(tree, x_mm=42_600),
        ),
        RuleCase(
            "tree_placed",
            "city.street_tree",
            "a trunk base past its extent",
            lambda: _replace(tree, extent=_shifted(tree.extent, min_z_mm=tree.z_mm + 1)),
        ),
        RuleCase(
            "premises_sign_and_storeys",
            "city.premises",
            "a sign with no text",
            lambda: _replace(shop, sign_text=()),
        ),
        RuleCase(
            "premises_sign_and_storeys",
            "city.premises",
            "a unit whose first storey is above its last",
            lambda: _replace(flats, first_storey=3, last_storey=1),
        ),
        RuleCase(
            "tile_grammar_versions_sorted",
            "city.tile",
            "a grammar pinned twice",
            lambda: _replace(tile, grammar_versions=(pin, pin)),
        ),
        RuleCase(
            "tile_grammar_versions_sorted",
            "city.tile",
            "grammars out of order",
            lambda: _replace(tile, grammar_versions=(pin, GrammarPin("box", 1, "0" * 64))),
        ),
    ]


def _facade_cases(south: Any, chamfer: Any, party: Any) -> list[RuleCase]:
    def case(what: str, make: Callable[[], object]) -> RuleCase:
        return RuleCase("facade_layout", "city.facade", what, make)

    courses = south.string_courses
    return [
        case("no parameters", lambda: _replace(south, parameters=())),
        case(
            "another subject's semantics",
            lambda: _replace(south, declared_semantics=DeclaredSemantics("facade", ())),
        ),
        case(
            "an ordinal that is not tier and edge",
            lambda: _replace(south, facade_ordinal=south.facade_ordinal + 1),
        ),
        case(
            "an edge ordinal past the tier stride",
            lambda: _replace(south, edge_ordinal=1_000_000, facade_ordinal=1_000_000),
        ),
        case(
            "bays and margins that miss the run",
            lambda: _replace(south, bays=_replace(south.bays, margin_end_mm=1)),
        ),
        case(
            "a long face with no bays",
            lambda: _replace(
                south, bays=BayLayout(0, 0, south.run_length_mm, 0), openings=(), cornice=()
            ),
        ),
        case(
            "a party wall with bays",
            lambda: _replace(party, bays=BayLayout(5, 2_800, 0, 0)),
        ),
        case("a neighbour line on a frontage", lambda: _replace(south, neighbour_top_mm=6_000)),
        case(
            "a frontage that faces no segment",
            lambda: _replace(south, faces_segment_identity=(), faces_curb_identity=()),
        ),
        case(
            "a rear face that faces a segment",
            lambda: _replace(party, exposure="rear", faces_segment_identity=(_OTHER_IDENTITY,)),
        ),
        case("a segment without its curb", lambda: _replace(south, faces_curb_identity=())),
        case(
            "a face whose first storey is above its last",
            lambda: _replace(south, first_storey=3, last_storey=2, band_top_mm=0, openings=()),
        ),
        case("a ground band too short", lambda: _replace(south, band_top_mm=3_999)),
        case(
            "a ground band on an upper face",
            lambda: _replace(FIXTURE.facades[5], band_top_mm=4_500),
        ),
        case(
            "openings on a face with no bays",
            lambda: _replace(chamfer, openings=south.openings),
        ),
        case(
            "an opening wider than its bay",
            lambda: _replace(south, openings=(_replace(south.openings[0], u_offset_mm=1_601),)),
        ),
        case(
            "openings on the ground storey's face above its storeys",
            lambda: _replace(south, openings=(_replace(south.openings[0], storeys=(1, 3)),)),
        ),
        case(
            "a string course too tall",
            lambda: _replace(
                south, string_courses=(_replace(courses[0], z_top_mm=4_701), courses[1])
            ),
        ),
        case(
            "string courses that overlap",
            lambda: _replace(
                south, string_courses=(courses[0], _replace(courses[1], z_bottom_mm=4_600))
            ),
        ),
        case(
            "cornice steps that overlap",
            lambda: _replace(
                south,
                cornice=(south.cornice[0], _replace(south.cornice[1], z_bottom_mm=10_550)),
            ),
        ),
        case(
            "a cornice too short",
            lambda: _replace(
                south, cornice=(south.cornice[0], _replace(south.cornice[1], z_top_mm=10_849))
            ),
        ),
    ]


def _bay_cases(bay: Any) -> list[RuleCase]:
    def case(what: str, make: Callable[[], object]) -> RuleCase:
        return RuleCase("bay_panels_tile", "city.ground_bay", what, make)

    riser, glazing, transom, fascia = bay.panels
    return [
        case(
            "panels that do not start at the base",
            lambda: _replace(
                bay, panels=(_replace(riser, z_bottom_mm=1), glazing, transom, fascia)
            ),
        ),
        case(
            "a panel past its bay",
            lambda: _replace(
                bay, panels=(riser, glazing, transom, _replace(fascia, u_end_mm=2_801))
            ),
        ),
        case(
            "panels that overlap",
            lambda: _replace(
                bay, panels=(riser, _replace(glazing, z_bottom_mm=500), transom, fascia)
            ),
        ),
        case(
            "panels that leave a gap",
            lambda: _replace(
                bay, panels=(riser, glazing, transom, _replace(fascia, u_end_mm=2_700))
            ),
        ),
        case(
            "an awning above the band",
            lambda: _replace(bay, awning=(_replace(bay.awning[0], wall_z_mm=4_501),)),
        ),
    ]


_RULE_CASES = _cases()


def test_every_named_rule_has_a_case():
    named = {rule.name for shape in _SHAPES.values() for rule in shape.rules}
    covered = {case.rule for case in _RULE_CASES}
    assert covered == named, sorted(named ^ covered)
    assert len(named) == 36


@pytest.mark.parametrize(
    "case", _RULE_CASES, ids=[f"{case.rule}: {case.what}" for case in _RULE_CASES]
)
def test_each_named_rule_refuses_its_case_on_its_own(case):
    shape = _SHAPES[case.shape]
    [rule] = [rule for rule in shape.rules if rule.name == case.rule]
    record = case.make()
    if case.fields_valid:
        shapes.validate_record(record, dataclasses.replace(shape, rules=()))
    for other in shape.rules:
        if other is not rule:
            other.check(record)
    with pytest.raises(GrammarError):
        rule.check(record)
    with pytest.raises(GrammarError):
        shapes.validate_record(record, shape)


def test_a_nested_rule_is_enforced_from_the_top_level_record():
    south = FIXTURE.facades[0]
    flat = Moulding(4_500, 4_500, 60)
    with pytest.raises(InvalidRecordError, match="bottom is below its top"):
        shapes.validate_record(
            _replace(south, string_courses=(flat, south.string_courses[1])),
            _SHAPES["city.facade"],
        )
    node = _BY_KIND["city.street_node"][0]
    inverted = _shifted(node.extent, min_x_mm=node.x_mm + 1)
    with pytest.raises(InvalidRecordError, match="min_x_mm is above max_x_mm"):
        shapes.validate_record(_replace(node, extent=inverted), _SHAPES["city.street_node"])
