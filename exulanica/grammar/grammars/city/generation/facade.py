"""The facade generator: a face on every tier edge, ground band first, and the doors people use.

**A building's faces agree.** Every facade parameter is face level, and each is derived with the
building as the subject, so a building's faces share one bay pitch target, one opening, one ground
band and one set of mouldings: the rhythm a single building has. The facade record states every
one, with its value and source, on every face, party walls included. This version derives them;
it refuses a facade parameter bound by a scope, because a face's parameters would then need the
binding's level, which a stage context does not carry.

**Exposure.** An edge on a lot frontage faces its curb and is ``frontage``. Any other edge lies on a
lot line: ``party_wall`` when a building stands across it, with ``neighbour_top_mm`` the height
above this building's base the neighbour's wall top reaches, up to this face's own top; ``flank``
for a side edge and ``rear`` for the back edge when no building stands across.

**Bays, by the pitch rule.** A face longer than 1200 mm that is not a party wall has
``count = max(round(run / target), ceil(run / 3500))`` bays of ``pitch = run // count``, the
remainder split into its two margins, smaller first; ``target`` is ``bay_pitch_mm``. The second
term keeps every pitch within the target architecture's 3.5 m maximum, so a door that fills a bay
stays within an entrance record's width.

**Upper storeys.** One opening grid covers every bay of every upper storey of a face. Its head
follows its treatment: ``plain`` has no band, projection or rise; ``lintel`` and ``hood`` have a
band, a hood always projecting; only an ``arch`` rises, at most half its width. A sill thickness is
0 exactly when its projection is. Sill, height and head are narrowed so an opening's top stays
within its storey; its width is at most two thirds of the smallest pitch of the building's bayed
faces and is centred in its bay. The two-thirds share of wall to window is authored and awaits
admitted statistics of pier widths.

**Mouldings.** A string course ``string_course_height_mm`` tall runs along the top of the ground
band on every face that has one and is not a party wall, projecting ``string_course_projection_mm``;
a projection of 0 is no string course. A cornice ``cornice_height_mm`` tall projecting
``cornice_projection_mm`` crowns every frontage face of the top tier: required by a cornice era,
derived from 1 mm, forbidden by a no-cornice era, 0, and optional otherwise, 0 being none.

**The ground band.** A building's ground floor is commercial when its primary frontage is a high
street or its typology admits no dwelling on the ground floor; otherwise it is a dwelling's.

* On a commercial frontage, the bay at the lot's threshold is the building's own door when it has
  upper storeys. The other bays, in each run between that door and the face's ends, form shop
  units of two, the last of a run taking three when the run is odd, and a run of one bay being a
  unit of its own. A unit's first bay is its door, with a transom over it and a fascia; the rest are
  shopfronts: a stall riser, glazing, a transom and a fascia. A corner lot's second frontage is
  shopfront bays of the unit at that end.
* On a dwelling's frontage, the bay at the threshold is the door and the others are wall.
* A flank or rear face has wall bays.

A door fills its bay's width (an even number of millimetres, so its centre is a whole one) and
stands from the ground to its transom, no taller than an entrance record holds, so the fascia and
transom are narrowed to fill the ground band above that height; it is recessed
``entrance_recess_mm``, and a building door carries wall where a shop's carries its fascia. The
threshold stands ``threshold_height_mm`` above the footway, which is exactly the building's base
above its frontage curb's back edge. An awning ``awning_projection_mm`` deep, level (no parameter
states a fall), with a ``awning_valance_mm`` valance, hangs from the bottom of the fascia over every
shop bay. A building with shops has one: its projection is derived from the least an awning record
holds, 300 mm, since the parameter's range starts at 0 and a record cannot state 1 to 299 mm; a
building without shops states 0, none.

**Extents.** A face's extent is its edge's plan box grown outward by its largest projection and
inward by its deepest recess, from its first storey's floor to its tier's top; a ground bay's and
an entrance's lie inside it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.grammar.contract import DeclaredSemantics, StageContext
from exulanica.grammar.errors import InvalidParameterError, InvalidRecordError
from exulanica.grammar.geometry import Extent, edge_run_length, integer_sqrt
from exulanica.grammar.grammars.city import facade, massing, parcels, streets
from exulanica.grammar.grammars.city.corners import strip_box
from exulanica.grammar.grammars.city.descriptor import (
    CITY_ADMISSIBLE_USES,
    CITY_GRAMMAR_VERSION,
    CITY_SURFACE,
)
from exulanica.grammar.grammars.city.generation.stage import (
    GeneratorStage,
    derived,
    entry,
    prior_records,
)
from exulanica.grammar.parameters import ParameterBinding

__all__ = ["MAXIMUM_PITCH_MM", "STAGE", "is_shop_bay", "shop_units"]

#: The target architecture's widest bay: no pitch this generator lays out exceeds it.
MAXIMUM_PITCH_MM: Final = 3_500
_LOTS_PER_BLOCK: Final = 10_000
_SEMANTICS: Final = DeclaredSemantics(facade.STAGE_ID, CITY_ADMISSIBLE_USES)
_FACADE_PARAMETERS: Final = tuple(
    sorted(spec.name for spec in CITY_SURFACE.parameters.for_stage(facade.STAGE_ID))
)


def is_shop_bay(bay: facade.GroundBayRecord) -> bool:
    """A shop's bay: a shopfront, or a door bay carrying a fascia."""
    return bay.bay_kind == "shopfront" or (
        bay.bay_kind == "entrance" and any(panel.role == "fascia" for panel in bay.panels)
    )


def shop_units(bays: Sequence[facade.GroundBayRecord]) -> list[list[facade.GroundBayRecord]]:
    """A face's shop units: runs of shop bays, each from its door, in order along the face."""
    units: list[list[facade.GroundBayRecord]] = []
    for bay in sorted(bays, key=lambda item: item.bay_ordinal):
        if not is_shop_bay(bay):
            continue
        starts = bay.bay_kind == "entrance"
        follows = units and units[-1][-1].bay_ordinal == bay.bay_ordinal - 1
        if starts or not follows:
            units.append([bay])
        else:
            units[-1].append(bay)
    return units


@dataclass(frozen=True, slots=True)
class _Values:
    """A building's facade parameters, by name."""

    values: dict[str, int | str]

    def __getitem__(self, name: str) -> int:
        return self.values[name]  # type: ignore[return-value]

    def bindings(self) -> tuple[ParameterBinding, ...]:
        return tuple(
            ParameterBinding(name, self.values[name], "derive") for name in _FACADE_PARAMETERS
        )


def _field(shape: object, name: str) -> Any:
    return next(field for field in shape.fields if field.name == name)  # type: ignore[attr-defined]


def _count(run: int, target: int) -> int:
    nearest = (2 * run + target) // (2 * target)
    widest = -(-run // MAXIMUM_PITCH_MM)
    return max(1, nearest, widest)


def _layout(run: int, exposure: str, target: int) -> facade.BayLayout:
    if exposure == "party_wall" or run <= facade.MINIMUM_BAYED_RUN_MM:
        return facade.BayLayout(0, 0, run, 0)
    count = _count(run, target)
    pitch = run // count
    rest = run - count * pitch
    return facade.BayLayout(count, pitch, rest // 2, rest - rest // 2)


def _edge(ring: tuple[tuple[int, int], ...], index: int) -> tuple[tuple[int, int], tuple[int, int]]:
    return ring[index], ring[(index + 1) % len(ring)]


def _neighbour(
    lot: parcels.ParcelRecord, edge: int, lots: Sequence[parcels.ParcelRecord]
) -> parcels.ParcelRecord | None:
    """The lot across one of ``lot``'s edges: one with a reversed, overlapping edge."""
    (ax, ay), (bx, by) = _edge(lot.boundary_mm, edge)
    for other in lots:
        if other.identity == lot.identity:
            continue
        ring = other.boundary_mm
        for index in range(len(ring)):
            (cx, cy), (dx, dy) = _edge(ring, index)
            vertical = ax == bx == cx == dx and (ay < by) != (cy < dy)
            if vertical and min(ay, by) < max(cy, dy) and min(cy, dy) < max(ay, by):
                return other
            level = ay == by == cy == dy and (ax < bx) != (cx < dx)
            if level and min(ax, bx) < max(cx, dx) and min(cx, dx) < max(ax, bx):
                return other
    return None


def _outward(start: tuple[int, int], end: tuple[int, int]) -> tuple[int, int]:
    """The outward unit normal of a counter-clockwise ring's axis-aligned edge."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    return (dy > 0) - (dy < 0), -((dx > 0) - (dx < 0))


def _face_box(
    start: tuple[int, int],
    end: tuple[int, int],
    outward: int,
    inward: int,
    low_z: int,
    high_z: int,
    u_range: tuple[int, int] | None = None,
) -> Extent:
    run = integer_sqrt(
        (end[0] - start[0]) * (end[0] - start[0]) + (end[1] - start[1]) * (end[1] - start[1])
    )
    if u_range is not None:
        first, last = u_range
        begin = (
            start[0] + (end[0] - start[0]) * first // run,
            start[1] + (end[1] - start[1]) * first // run,
        )
        finish = (
            start[0] + (end[0] - start[0]) * last // run,
            start[1] + (end[1] - start[1]) * last // run,
        )
        start, end = begin, finish
    nx, ny = _outward(start, end) if start != end else (0, 0)
    xs = [start[0], end[0], start[0] + nx * outward, start[0] - nx * inward]
    ys = [start[1], end[1], start[1] + ny * outward, start[1] - ny * inward]
    return Extent(min(xs), min(ys), low_z, max(xs), max(ys), high_z)


def _derive_values(
    context: StageContext,
    ordinal: int,
    building: massing.MassingRecord,
    step: int,
    smallest_pitch: int,
    commercial: bool,
) -> _Values:
    for name in _FACADE_PARAMETERS:
        if name in context.parameters:
            raise InvalidParameterError(
                f"{name} is bound by a scope; this facade stage version derives every facade "
                "parameter per building"
            )
    values: dict[str, int | str] = {}

    def put(name: str, **narrowing: object) -> int:
        values[name] = derived(context, name, ordinal, **narrowing)  # type: ignore[arg-type]
        return values[name]  # type: ignore[return-value]

    era = entry("era", building.era)
    ground = building.ground_storey_height_mm
    upper = building.upper_storey_height_mm
    put("bay_pitch_mm")
    # A door stands from the ground to its transom, and an entrance record holds a door no taller
    # than its height field's maximum: the fascia and transom together fill the rest.
    tallest_door = _field(facade.ENTRANCE_SHAPE, "height_mm").maximum
    transom_spec = CITY_SURFACE.parameters.get("transom_height_mm")
    fascia = put("fascia_height_mm", minimum=ground - tallest_door - transom_spec.maximum)
    put("transom_height_mm", minimum=ground - tallest_door - fascia)
    put("stall_riser_height_mm")
    put("entrance_recess_mm")
    put("threshold_height_mm", minimum=step, maximum=step)
    if commercial:
        put("awning_projection_mm", minimum=_field(facade.AWNING_SHAPE, "projection_mm").minimum)
    else:
        put("awning_projection_mm", maximum=0)
    put("awning_valance_mm")
    put("cornice_height_mm")
    if era["cornice"] == "required":
        put("cornice_projection_mm", minimum=1)
    elif era["cornice"] == "none":
        put("cornice_projection_mm", maximum=0)
    else:
        put("cornice_projection_mm")
    put("string_course_height_mm")
    put("string_course_projection_mm")
    treatment = values["head_treatment"] = derived(context, "head_treatment", ordinal)
    put("reveal_depth_mm")
    sill_projection = put("sill_projection_mm")
    put("sill_thickness_mm", **({"maximum": 0} if sill_projection == 0 else {"minimum": 1}))
    width = put("opening_width_mm", maximum=smallest_pitch * 2 // 3)
    if treatment == "plain":
        band = put("head_band_mm", maximum=0)
        put("head_projection_mm", maximum=0)
    else:
        band = put("head_band_mm", minimum=1)
        put("head_projection_mm", **({"minimum": 1} if treatment == "hood" else {}))
    rise = put(
        "head_rise_mm",
        **({"minimum": 1, "maximum": width // 2} if treatment == "arch" else {"maximum": 0}),
    )
    spec = CITY_SURFACE.parameters.get("opening_height_mm")
    sill = put("sill_height_mm", maximum=upper - spec.minimum - rise - band)
    put("opening_height_mm", maximum=upper - sill - rise - band)
    if (
        ground
        - values["fascia_height_mm"]
        - values["transom_height_mm"]
        - values["stall_riser_height_mm"]
        < 1
    ):  # type: ignore[operator]
        raise InvalidRecordError(f"building {building.identity}'s ground band leaves no glazing")
    return _Values(values)


def _generate(context: StageContext) -> Iterator[object]:
    buildings = prior_records(context, massing.STAGE_ID, massing.MassingRecord)
    lots = {
        record.identity: record
        for record in prior_records(context, parcels.STAGE_ID, parcels.ParcelRecord)
    }
    lot_list = list(lots.values())
    curbs = {
        record.identity: record
        for record in prior_records(context, streets.STAGE_ID, streets.CurbEdgeRecord)
    }
    segments = {
        record.identity: record
        for record in prior_records(context, streets.STAGE_ID, streets.StreetSegmentRecord)
    }
    block_ordinals = {
        record.identity: record.block_ordinal
        for record in prior_records(context, streets.STAGE_ID, streets.BlockRecord)
    }
    by_lot = {building.parcel_identity: building for building in buildings}

    for building in buildings:
        lot = lots[building.parcel_identity]
        ordinal = block_ordinals[lot.block_identity] * _LOTS_PER_BLOCK + lot.parcel_ordinal
        frontage_curbs = {row.edge_ordinal: curbs[row.curb_identity] for row in lot.frontages}
        primary = lot.frontages[0]
        primary_curb = curbs[primary.curb_identity]
        step = building.base_elevation_mm - strip_box(primary_curb).max_z_mm
        if step < 0:
            raise InvalidRecordError(f"building {building.identity} stands below its footway")
        hierarchy = segments[primary_curb.segment_identity].hierarchy
        commercial = (
            hierarchy == "high_street"
            or "residential" not in entry("typology", building.typology)["ground_floor_uses"]
        )
        base = building.base_elevation_mm

        # Every face: its tier, edge, exposure and layout, before any value is derived.
        faces = []
        for tier_index, tier in enumerate(building.tiers):
            ring = tier.ring_mm
            for edge in range(len(ring)):
                run = edge_run_length(ring, edge)
                if edge in frontage_curbs:
                    exposure = "frontage"
                    neighbour_top = 0
                else:
                    across = _neighbour(lot, edge, lot_list)
                    other = by_lot.get(across.identity) if across is not None else None
                    if other is not None:
                        exposure = "party_wall"
                        other_top = other.base_elevation_mm + (
                            massing.tier_top_mm(other, other.tiers[-1]) - other.base_elevation_mm
                        )
                        own_top = massing.tier_top_mm(building, tier) - base
                        neighbour_top = max(0, min(own_top, other_top - base))
                    else:
                        exposure = "rear" if edge in ((primary.edge_ordinal + 2) % 4,) else "flank"
                        neighbour_top = 0
                faces.append((tier_index, tier, edge, run, exposure, neighbour_top))
        # A building's bay pitch target and the pitches its faces take.
        target = derived(context, "bay_pitch_mm", ordinal)
        pitches = [
            _layout(run, exposure, target).pitch_mm  # type: ignore[arg-type]
            for _t, _tier, _e, run, exposure, _n in faces
            if _layout(run, exposure, target).count  # type: ignore[arg-type]
        ]
        values = _derive_values(context, ordinal, building, step, min(pitches), commercial)
        ground = building.ground_storey_height_mm
        fascia, transom, stall = (
            values["fascia_height_mm"],
            values["transom_height_mm"],
            values["stall_riser_height_mm"],
        )
        glazing_top = ground - fascia - transom
        door_top = glazing_top
        recess = values["entrance_recess_mm"]
        awning = (
            (
                facade.Awning(
                    ground - fascia,
                    ground - fascia,
                    values["awning_projection_mm"],
                    values["awning_valance_mm"],
                ),
            )
            if values["awning_projection_mm"]
            else ()
        )
        projections = [
            values["cornice_projection_mm"],
            values["string_course_projection_mm"],
            values["sill_projection_mm"],
            values["head_projection_mm"],
            values["awning_projection_mm"],
        ]
        deepest = max(recess, values["reveal_depth_mm"])

        for tier_index, tier, edge, run, exposure, neighbour_top in faces:
            ring = tier.ring_mm
            start, end = _edge(ring, edge)
            layout = _layout(run, exposure, target)  # type: ignore[arg-type]
            facade_ordinal = tier_index * facade.FACADE_TIER_STRIDE + edge
            identity = context.identity("facade", building.identity, facade_ordinal)
            first, last = tier.first_storey, tier.last_storey
            floor = massing.storey_floor_mm(building, first) - base
            top = massing.tier_top_mm(building, tier) - base
            openings: tuple[facade.OpeningGrid, ...] = ()
            upper_storeys = tuple(storey for storey in range(max(1, first), last + 1))
            if layout.count and upper_storeys:
                width = values["opening_width_mm"]
                openings = (
                    facade.OpeningGrid(
                        storeys=upper_storeys,
                        u_offset_mm=(layout.pitch_mm - width) // 2,
                        width_mm=width,
                        height_mm=values["opening_height_mm"],
                        sill_height_mm=values["sill_height_mm"],
                        reveal_depth_mm=values["reveal_depth_mm"],
                        sill_projection_mm=values["sill_projection_mm"],
                        sill_thickness_mm=values["sill_thickness_mm"],
                        head_treatment=values.values["head_treatment"],  # type: ignore[arg-type]
                        head_rise_mm=values["head_rise_mm"],
                        head_band_mm=values["head_band_mm"],
                        head_projection_mm=values["head_projection_mm"],
                    ),
                )
            courses: tuple[facade.Moulding, ...] = ()
            if first == 0 and exposure != "party_wall" and values["string_course_projection_mm"]:
                courses = (
                    facade.Moulding(
                        ground,
                        ground + values["string_course_height_mm"],
                        values["string_course_projection_mm"],
                    ),
                )
            cornice: tuple[facade.Moulding, ...] = ()
            if (
                exposure == "frontage"
                and tier_index == len(building.tiers) - 1
                and values["cornice_projection_mm"]
            ):
                cornice = (
                    facade.Moulding(
                        top - values["cornice_height_mm"], top, values["cornice_projection_mm"]
                    ),
                )
            curb = frontage_curbs.get(edge)
            bays: list[facade.GroundBayRecord] = []
            entrances: list[facade.EntranceRecord] = []
            if first == 0 and layout.count:
                kinds = _bay_kinds(
                    layout,
                    exposure,
                    commercial,
                    edge == primary.edge_ordinal,
                    lot.threshold_offset_mm,
                    building.storeys,
                )
                for bay_ordinal, kind in enumerate(kinds):
                    u0 = layout.margin_start_mm + bay_ordinal * layout.pitch_mm
                    u1 = u0 + layout.pitch_mm
                    panels = _panels(kind, u0, u1, ground, fascia, transom, stall, recess)
                    bay_awning = awning if kind in ("shopfront", "shop_door") else ()
                    bay_identity = context.identity("ground_bay", identity, bay_ordinal)
                    bays.append(
                        facade.GroundBayRecord(
                            identity=bay_identity,
                            facade_identity=identity,
                            bay_ordinal=bay_ordinal,
                            bay_kind={
                                "shop_door": "entrance",
                                "building_door": "entrance",
                                "wall": "blank",
                            }.get(kind, kind),
                            u_start_mm=u0,
                            width_mm=layout.pitch_mm,
                            panels=panels,
                            awning=bay_awning,
                            extent=_face_box(
                                start,
                                end,
                                values["awning_projection_mm"] if bay_awning else 0,
                                max((panel.recess_mm for panel in panels), default=0),
                                base,
                                base + ground,
                                (u0, u1),
                            ),
                        )
                    )
                    if kind in ("shop_door", "building_door"):
                        centre = u0 + layout.pitch_mm // 2
                        x = start[0] + (end[0] - start[0]) * centre // run
                        y = start[1] + (end[1] - start[1]) * centre // run
                        entrance_ordinal = len(entrances)
                        entrances.append(
                            facade.EntranceRecord(
                                identity=context.identity("entrance", identity, entrance_ordinal),
                                facade_identity=identity,
                                bay_identity=bay_identity,
                                entrance_ordinal=entrance_ordinal,
                                u_centre_mm=centre,
                                width_mm=layout.pitch_mm - layout.pitch_mm % 2,
                                height_mm=door_top,
                                recess_mm=recess,
                                step_height_mm=values["threshold_height_mm"],
                                threshold_x_mm=x,
                                threshold_y_mm=y,
                                threshold_z_mm=base,
                                approach_curb_identity=(curb.identity,) if curb is not None else (),
                                extent=_face_box(
                                    start, end, 0, recess, base, base + door_top, (u0, u1)
                                ),
                            )
                        )
            draft = facade.FacadeRecord(
                building_identity=building.identity,
                grammar_version=CITY_GRAMMAR_VERSION,
                parameters=values.bindings(),
                seed=context.seed,
                output_digest="0" * 64,
                declared_semantics=_SEMANTICS,
                identity=identity,
                facade_ordinal=facade_ordinal,
                tier_ordinal=tier_index,
                edge_ordinal=edge,
                exposure=exposure,
                faces_segment_identity=(curb.segment_identity,) if curb is not None else (),
                faces_curb_identity=(curb.identity,) if curb is not None else (),
                run_length_mm=run,
                first_storey=first,
                last_storey=last,
                band_top_mm=ground if first == 0 else 0,
                bays=layout,
                openings=openings,
                string_courses=courses,
                cornice=cornice,
                neighbour_top_mm=neighbour_top,
                extent=_face_box(start, end, max(projections), deepest, base + floor, base + top),
            )
            yield dataclasses.replace(
                draft,
                output_digest=facade.facade_output_digest(draft, tuple(bays), tuple(entrances)),
            )
            yield from bays
            yield from entrances


def _bay_kinds(
    layout: facade.BayLayout,
    exposure: str,
    commercial: bool,
    primary: bool,
    threshold: int,
    storeys: int,
) -> list[str]:
    """Each bay's part in the ground band, by the module's rule."""
    count = layout.count
    if exposure != "frontage":
        return ["wall"] * count
    door = min(count - 1, max(0, (threshold - layout.margin_start_mm) // layout.pitch_mm))
    if not commercial:
        kinds = ["wall"] * count
        if primary:
            kinds[door] = "building_door"
        return kinds
    if not primary:
        return ["shopfront"] * count
    kinds = [""] * count
    shop_bays = list(range(count))
    if storeys > 1 and count > 1:
        kinds[door] = "building_door"
        shop_bays.remove(door)
    runs: list[list[int]] = []
    for index in shop_bays:
        if runs and runs[-1][-1] == index - 1:
            runs[-1].append(index)
        else:
            runs.append([index])
    for run in runs:
        groups = [run[position : position + 2] for position in range(0, len(run), 2)]
        if len(groups) > 1 and len(groups[-1]) == 1:
            groups[-2].extend(groups.pop())
        for group in groups:
            kinds[group[0]] = "shop_door"
            for index in group[1:]:
                kinds[index] = "shopfront"
    return kinds


def _panels(
    kind: str, u0: int, u1: int, ground: int, fascia: int, transom: int, stall: int, recess: int
) -> tuple[facade.GroundPanel, ...]:
    glazing_top = ground - fascia - transom
    band = ground - fascia
    if kind == "wall":
        return (facade.GroundPanel("wall", u0, u1, 0, ground, 0),)
    if kind == "shopfront":
        panels = [
            facade.GroundPanel("stall_riser", u0, u1, 0, stall, 0),
            facade.GroundPanel("glazing", u0, u1, stall, glazing_top, 0),
        ]
    else:
        panels = [facade.GroundPanel("door", u0, u1, 0, glazing_top, recess)]
    if transom:
        panels.append(
            facade.GroundPanel(
                "transom", u0, u1, glazing_top, band, 0 if kind == "shopfront" else recess
            )
        )
    panels.append(
        facade.GroundPanel("wall" if kind == "building_door" else "fascia", u0, u1, band, ground, 0)
    )
    return tuple(panels)


STAGE: Final = GeneratorStage(
    facade.STAGE_ID,
    facade.STAGE_VERSION,
    (facade.FACADE_SHAPE, facade.BAY_SHAPE, facade.ENTRANCE_SHAPE),
    _generate,
)
