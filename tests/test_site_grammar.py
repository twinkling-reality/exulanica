"""The site grammar: a world of any kind but the town, laid out from its kind's plan.

The plans here are built from the hand-written fixture kinds in ``tests/fixtures/world-kinds``
(test fixtures, not kinds any person or model made). Expected figures come from the plan and from
geometry computed here, never from the layout code under test.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from exulanica.grammar.errors import InvalidParameterError, InvalidRecordError
from exulanica.grammar.grammars.site import (
    SITE_DESCRIPTOR_PATH,
    check_site_records,
    generate_site,
    site_records,
)
from exulanica.grammar.grammars.site.layout import SPACING
from exulanica.grammar.grammars.site.plan import (
    FixturePart,
    Holding,
    Look,
    SitePlan,
    Span,
    StructurePart,
)
from exulanica.grammar.grammars.site.records import (
    SiteExtentRecord,
    SiteFixtureRecord,
    SitePathRecord,
    SiteStructureRecord,
    SiteWallRecord,
    SiteZoneRecord,
)
from exulanica.grammar.subjects import subject_identity
from exulanica.world.kinds.document import read_kind

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"
SEED = "5" * 64
OTHER_SEED = "6" * 64
ROOT = "0b6f3a1e-2c4d-5e6f-8a9b-0c1d2e3f4a5b"


def _kind(name: str):  # type: ignore[no-untyped-def]
    return read_kind(json.loads((FIXTURES / f"fixture-{name}.json").read_text(encoding="utf-8")))


def _plan(name: str) -> SitePlan:
    kind = _kind(name)
    return kind.plan(kind.values(kind.presets[0][0]))


def _records(plan: SitePlan, seed: str = SEED) -> tuple[object, ...]:
    return site_records(generate_site(plan, seed=seed, subject_identity=ROOT))


def test_a_site_is_the_same_records_for_the_same_seed_and_another_for_another():
    plan = _plan("farm")
    first = generate_site(plan, seed=SEED, subject_identity=ROOT)
    again = generate_site(plan, seed=SEED, subject_identity=ROOT)
    other = generate_site(plan, seed=OTHER_SEED, subject_identity=ROOT)
    assert first.receipt.output_digest == again.receipt.output_digest
    assert site_records(first) == site_records(again)
    assert other.receipt.output_digest != first.receipt.output_digest
    assert first.receipt.grammar_id == "site" and first.receipt.grammar_version == 1


def test_every_record_states_the_identity_its_rule_derives():
    records = _records(_plan("farm"))
    check_site_records(records, root_identity=ROOT)
    extent = next(r for r in records if isinstance(r, SiteExtentRecord))
    # Re-derived here from the subject rule itself, not read back from the layout.
    assert extent.identity == subject_identity(
        grammar_id="site",
        root_identity=ROOT,
        subject_kind="site_extent",
        owner_identity=ROOT,
        ordinal=0,
    )
    zones = [r for r in records if isinstance(r, SiteZoneRecord)]
    for zone in zones:
        assert zone.identity == subject_identity(
            grammar_id="site",
            root_identity=ROOT,
            subject_kind="site_zone",
            owner_identity=ROOT,
            ordinal=zone.ordinal,
        )


def test_a_record_with_a_changed_identity_is_refused():
    records = list(_records(_plan("farm")))
    index = next(i for i, r in enumerate(records) if isinstance(r, SiteZoneRecord))
    zone = records[index]
    import dataclasses

    records[index] = dataclasses.replace(zone, ordinal=zone.ordinal + 7)  # type: ignore[type-var]
    with pytest.raises(InvalidRecordError, match="not the identity its rule derives"):
        check_site_records(records, root_identity=ROOT)


def test_the_plan_holds_every_zone_and_count_the_kind_states():
    plan = _plan("farm")
    records = _records(plan)
    zones = {r.zone_key for r in records if isinstance(r, SiteZoneRecord)}
    assert zones == {zone.key for zone in plan.zones}
    counted = Counter(r.part_key for r in records if isinstance(r, SiteStructureRecord))
    holdings = {h.part: h.count for z in plan.zones for h in z.holds}
    for part, number in counted.items():
        span = holdings[part]
        assert span.minimum <= number <= span.maximum


def test_every_zone_fronts_a_path():
    """Each zone's gate lies on the edge of the spine or the cross path, so every zone is reached
    from the entry: checked against the path rectangles, not the layout's own lot allotment."""
    for name in ("farm", "cafe", "site"):
        records = _records(_plan(name))
        paths = [r for r in records if isinstance(r, SitePathRecord)]
        for zone in (r for r in records if isinstance(r, SiteZoneRecord)):
            x, y = zone.gate_x_mm, zone.gate_y_mm
            assert any(
                p.min_x_mm <= x <= p.max_x_mm and p.min_y_mm <= y <= p.max_y_mm for p in paths
            ), (name, zone.zone_key)


def _footprint(record: SiteFixtureRecord) -> tuple[int, int, int, int]:
    along_x, along_y = (
        (record.width_mm, record.depth_mm)
        if record.yaw_quarter_turns % 2 == 0
        else (record.depth_mm, record.width_mm)
    )
    return (
        record.x_mm - along_x // 2,
        record.y_mm - along_y // 2,
        record.x_mm - along_x // 2 + along_x,
        record.y_mm - along_y // 2 + along_y,
    )


def test_a_fixture_lies_inside_the_site_by_its_footprint_as_it_is_turned():
    """A long fixture along the site's edge lies inside it, as the society's place blocks it; a
    millimetre past the edge does not, whichever way it is turned."""
    import dataclasses

    from exulanica.grammar.grammars.site import _inside

    records = _records(_plan("farm"))
    extent = next(r for r in records if isinstance(r, SiteExtentRecord))
    fixture = next(r for r in records if isinstance(r, SiteFixtureRecord))
    shelf = dataclasses.replace(
        fixture, width_mm=3000, depth_mm=300, yaw_quarter_turns=0, x_mm=1500, y_mm=150
    )
    assert _inside(shelf, extent)
    assert not _inside(dataclasses.replace(shelf, x_mm=1499), extent)
    assert not _inside(dataclasses.replace(shelf, y_mm=149), extent)
    far = dataclasses.replace(shelf, x_mm=extent.width_mm - 1500)
    assert _inside(far, extent)
    assert not _inside(dataclasses.replace(far, x_mm=extent.width_mm - 1499), extent)
    turned = dataclasses.replace(shelf, yaw_quarter_turns=1, x_mm=150, y_mm=1500)
    assert _inside(turned, extent)
    assert not _inside(dataclasses.replace(turned, x_mm=149), extent)
    assert not _inside(dataclasses.replace(turned, y_mm=1499), extent)


def _apart(a: tuple[int, int, int, int], b: tuple[int, int, int, int], gap: int) -> bool:
    return a[2] + gap <= b[0] or b[2] + gap <= a[0] or a[3] + gap <= b[1] or b[3] + gap <= a[1]


def test_fixtures_in_a_zone_keep_their_clearance_from_each_other_and_from_structures():
    for name in ("farm", "site"):
        plan = _plan(name)
        clearance = SPACING[plan.enclosure].clearance
        records = _records(plan)
        zone_ids = {r.identity for r in records if isinstance(r, SiteZoneRecord)}
        fixtures = [
            _footprint(r)
            for r in records
            if isinstance(r, SiteFixtureRecord) and r.owner_identity in zone_ids
        ]
        structures = [
            (r.min_x_mm, r.min_y_mm, r.max_x_mm, r.max_y_mm)
            for r in records
            if isinstance(r, SiteStructureRecord)
        ]
        for index, first in enumerate(fixtures):
            for second in fixtures[index + 1 :]:
                assert _apart(first, second, clearance), (name, first, second)
            for structure in structures:
                assert _apart(first, structure, clearance), (name, first, structure)


def test_a_structure_too_wide_for_its_zone_is_refused_with_its_figures():
    plan = _plan("farm")
    barn = plan.by_key()["barn"]
    assert isinstance(barn, StructurePart)
    import dataclasses

    huge = dataclasses.replace(barn, width_mm=Span(200000, 200000, 1))
    parts = tuple(huge if part.key == "barn" else part for part in plan.parts)
    widened = dataclasses.replace(plan, parts=parts)
    with pytest.raises(InvalidParameterError, match=r"side of the spine facing \w+ is \d+ mm long"):
        _records(widened)


def test_a_room_too_small_for_its_beds_is_refused_by_name():
    plan = _plan("farm")
    import dataclasses

    bed = plan.by_key()["bed"]
    assert isinstance(bed, FixturePart)
    wide_bed = dataclasses.replace(bed, width_mm=9000)
    parts = tuple(wide_bed if part.key == "bed" else part for part in plan.parts)
    with pytest.raises(InvalidParameterError, match="do not fit back_wall"):
        _records(dataclasses.replace(plan, parts=parts))


def test_a_wall_s_openings_lie_inside_it():
    for name in ("farm", "cafe", "site"):
        for wall in (r for r in _records(_plan(name)) if isinstance(r, SiteWallRecord)):
            length = (wall.end_x_mm - wall.start_x_mm) + (wall.end_y_mm - wall.start_y_mm)
            for opening in wall.openings:
                assert opening.offset_mm >= 0
                assert opening.offset_mm + opening.width_mm <= length


def test_an_indoor_site_has_its_entrance_door_in_its_outer_wall_at_the_spine():
    plan = _plan("cafe")
    records = _records(plan)
    extent = next(r for r in records if isinstance(r, SiteExtentRecord))
    outer = [
        r for r in records if isinstance(r, SiteWallRecord) and r.owner_identity == extent.identity
    ]
    assert len(outer) == 4
    south = next(
        w for w in outer if w.start_y_mm == w.end_y_mm and w.start_y_mm < plan.depth_mm // 2
    )
    door = next(o for o in south.openings if o.kind == "door")
    middle = south.start_x_mm + door.offset_mm + door.width_mm // 2
    assert middle == extent.entry_x_mm
    assert door.width_mm == plan.entry_width_mm


def test_a_plan_with_a_holding_of_an_unknown_part_is_refused():
    plan = _plan("farm")
    import dataclasses

    zone = dataclasses.replace(
        plan.zones[0], holds=(Holding("no_such_part", Span.fixed(1), "row"),)
    )
    with pytest.raises(InvalidParameterError, match="no_such_part"):
        dataclasses.replace(plan, zones=(zone, *plan.zones[1:]))


def test_a_look_names_a_family_of_the_closed_list():
    with pytest.raises(InvalidParameterError, match="no look family"):
        Look("spaceship", "hull")


def test_the_descriptor_states_no_projection_and_no_parameter():
    descriptor = json.loads(SITE_DESCRIPTOR_PATH.read_text(encoding="utf-8"))
    assert descriptor["admissible_uses"] == [] and descriptor["parameters"] == []
