"""What the page draws of a site world: every part as a slot a style pack dresses, and what a person
walking may stand on and must keep out of.

A site world is not baked. Its drawing is a document, ``exulanica.site-drawing/v1``, made from the
records its receipt generates again (:func:`site_drawing`) and served only to the world whose
snapshot names that receipt. It states, in the site's own frame (x east, y north, z up, integer
millimetres from the site's south-west corner; the region's east is x and its south is minus y):

* **slots**, one per drawn piece, in the shape agreed with the style packs: the piece's stable
  identity, its look role (``family.leaf``), the base centre of its box, its quarter turns, its
  box (width along its front, depth, height), its front (+y of the slot), its family's fit
  (``contain``, ``fill``, ``tile`` or ``surface``, the look-family catalog's), the engine's own
  primitive when no pack dresses it (``box``, ``plane``, ``gable`` or ``none``), and for a
  surface its UV frame: an origin and two in-plane axes each 1,000 mm long, so a material is laid
  at physical scale. Grounds, paths, areas and floors are planes stacked a few millimetres apart
  so none fights another for the same pixels; walls are boxes between their openings, with a
  lintel over each door; a door is a fill slot drawn by a pack or left open; a roof is a slab or a
  gable over its structure;
* **walk**: the level floor a person exploring stands on and the boxes they keep out of (wall
  pieces, blocking fixtures and water), so a person walks into a structure through its door and
  round its furniture, never through a wall;
* **seats**: each seat's height, so a person resting is drawn on it.

A slot's identity is its record's subject identity, or that identity with the piece it names
(``:wall:2``, ``:lintel:0``, ``:roof``, ``:door:0``), so a pack's variant chosen by identity is the
same on every load. Nothing here decides a look; a pack never changes a slot.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.grammars.site.records import (
    SiteAreaRecord,
    SiteExtentRecord,
    SiteFixtureRecord,
    SitePathRecord,
    SiteRoomRecord,
    SiteStructureRecord,
    SiteWallRecord,
    SiteZoneRecord,
)
from exulanica.world.kinds.catalogs import load_kind_catalogs

__all__ = ["DRAWING_PROFILE", "LAYER_MM", "site_drawing", "site_drawing_sha256"]

DRAWING_PROFILE: Final = "exulanica.site-drawing/v1"
#: How far above the ground each kind of surface lies, so planes never share a height.
LAYER_MM: Final = {"ground": 0, "zone": 6, "path": 12, "area": 18, "floor": 24}
#: A flat roof's slab, and a gable's rise per millimetre of its span (seven twentieths, a pitch
#: of about 35 degrees), as integers.
ROOF_SLAB_MM: Final = 200
GABLE_RISE_NUMERATOR: Final = 7
GABLE_RISE_DENOMINATOR: Final = 20
#: The height a person rests at on a seat that states no more: half its height, at most a chair's.
SEAT_HEIGHT_MAXIMUM_MM: Final = 460
_UNIT: Final = 1_000


def _fit(family: str) -> str:
    return load_kind_catalogs().families[family].fit


def _slot(
    identity: str,
    part: str,
    family: str,
    leaf: str,
    base: Sequence[int],
    yaw: int,
    box: Sequence[int],
    primitive: str,
    *,
    uv: Mapping[str, Sequence[int]] | None = None,
    label: str = "",
) -> dict[str, Any]:
    slot: dict[str, Any] = {
        "identity": identity,
        "part": part,
        "label": label,
        "lookRole": f"{family}.{leaf}",
        "positionMm": [int(base[0]), int(base[1]), int(base[2])],
        "yawQuarterTurns": yaw,
        "boxMm": [int(box[0]), int(box[1]), int(box[2])],
        "front": "+y",
        "fit": _fit(family),
        "primitive": primitive,
    }
    if uv is not None:
        slot["uvFrame"] = {key: [int(v) for v in value] for key, value in uv.items()}
    return slot


def _plane(
    identity: str,
    part: str,
    family: str,
    leaf: str,
    rect: tuple[int, int, int, int],
    z: int,
    label: str,
) -> dict[str, Any]:
    x0, y0, x1, y1 = rect
    return _slot(
        identity,
        part,
        family,
        leaf,
        ((x0 + x1) // 2, (y0 + y1) // 2, z),
        0,
        (x1 - x0, y1 - y0, 0),
        "plane",
        uv={"originMm": [x0, y0, z], "uAxisMm": [_UNIT, 0, 0], "vAxisMm": [0, _UNIT, 0]},
        label=label,
    )


def _wall_slots(wall: SiteWallRecord, label: str) -> tuple[list[dict[str, Any]], list[list[int]]]:
    """A wall as boxes between its openings, a lintel over each opening lower than the wall, and
    a fill slot in each door; with the boxes a person keeps out of."""
    along_x = wall.start_y_mm == wall.end_y_mm
    length = (wall.end_x_mm - wall.start_x_mm) + (wall.end_y_mm - wall.start_y_mm)
    yaw = 0 if along_x else 1
    slots: list[dict[str, Any]] = []
    blocks: list[list[int]] = []

    def at(offset: int) -> tuple[int, int]:
        return (
            (wall.start_x_mm + offset, wall.start_y_mm)
            if along_x
            else (wall.start_x_mm, wall.start_y_mm + offset)
        )

    def piece(kind: str, index: int, start: int, end: int, z: int, height: int) -> None:
        mid = at((start + end) // 2)
        width = end - start
        slots.append(
            _slot(
                f"{wall.identity}:{kind}:{index}",
                wall.part_key,
                wall.look_family,
                wall.look_leaf,
                (mid[0], mid[1], z),
                yaw,
                (width, wall.thickness_mm, height),
                "box",
                uv={
                    "originMm": [*at(start), z],
                    "uAxisMm": [_UNIT, 0, 0] if along_x else [0, _UNIT, 0],
                    "vAxisMm": [0, 0, _UNIT],
                },
                label=label,
            )
        )
        if z == 0:
            half = wall.thickness_mm // 2
            a, b = at(start), at(end)
            blocks.append(
                [a[0], a[1] - half, b[0], b[1] + half]
                if along_x
                else [a[0] - half, a[1], b[0] + half, b[1]]
            )

    reached = 0
    pieces = 0
    for index, opening in enumerate(wall.openings):
        if opening.offset_mm > reached:
            piece("wall", pieces, reached, opening.offset_mm, 0, wall.height_mm)
            pieces += 1
        top = opening.height_mm
        if top < wall.height_mm:
            piece(
                "lintel",
                index,
                opening.offset_mm,
                opening.offset_mm + opening.width_mm,
                top,
                wall.height_mm - top,
            )
        if opening.kind == "door":
            mid = at(opening.offset_mm + opening.width_mm // 2)
            slots.append(
                _slot(
                    f"{wall.identity}:door:{index}",
                    wall.part_key,
                    "door",
                    "default",
                    (mid[0], mid[1], 0),
                    yaw,
                    (opening.width_mm, wall.thickness_mm, top),
                    "none",
                    label=label,
                )
            )
        reached = opening.offset_mm + opening.width_mm
    if reached < length:
        piece("wall", pieces, reached, length, 0, wall.height_mm)
    return slots, blocks


def site_drawing(
    *,
    world_id: str,
    receipt: Mapping[str, Any],
    receipt_sha256: str,
    records: Sequence[object],
) -> dict[str, Any]:
    """The drawing a site world's records make, as one canonical document."""
    labels = {key: str(use["label"]) for key, use in receipt["society"]["uses"].items()}
    extent = next(r for r in records if isinstance(r, SiteExtentRecord))
    slots: list[dict[str, Any]] = []
    blocks: list[list[int]] = []
    keep_out: list[list[int]] = []
    seats: list[dict[str, Any]] = []
    slots.append(
        _plane(
            f"{extent.identity}:ground",
            receipt["kind"]["kind"],
            extent.ground_family,
            extent.ground_leaf,
            (0, 0, extent.width_mm, extent.depth_mm),
            LAYER_MM["ground"],
            "",
        )
    )
    for record in records:
        if isinstance(record, SiteZoneRecord):
            slots.append(
                _plane(
                    record.identity,
                    record.zone_key,
                    record.ground_family,
                    record.ground_leaf,
                    (record.min_x_mm, record.min_y_mm, record.max_x_mm, record.max_y_mm),
                    LAYER_MM["zone"],
                    "",
                )
            )
        elif isinstance(record, SitePathRecord):
            slots.append(
                _plane(
                    record.identity,
                    record.part_key,
                    record.look_family,
                    record.look_leaf,
                    (record.min_x_mm, record.min_y_mm, record.max_x_mm, record.max_y_mm),
                    LAYER_MM["path"],
                    labels.get(record.part_key, ""),
                )
            )
        elif isinstance(record, SiteAreaRecord):
            rect = (record.min_x_mm, record.min_y_mm, record.max_x_mm, record.max_y_mm)
            slots.append(
                _plane(
                    record.identity,
                    record.part_key,
                    record.look_family,
                    record.look_leaf,
                    rect,
                    LAYER_MM["area"],
                    labels.get(record.part_key, ""),
                )
            )
            if "water" in record.roles:
                keep_out.append(list(rect))
        elif isinstance(record, SiteRoomRecord):
            slots.append(
                _plane(
                    record.identity,
                    record.part_key,
                    record.floor_family,
                    record.floor_leaf,
                    (record.min_x_mm, record.min_y_mm, record.max_x_mm, record.max_y_mm),
                    LAYER_MM["floor"],
                    labels.get(record.part_key, ""),
                )
            )
        elif isinstance(record, SiteStructureRecord):
            width = record.max_x_mm - record.min_x_mm
            depth = record.max_y_mm - record.min_y_mm
            height = record.storeys * record.storey_height_mm
            middle = (
                (record.min_x_mm + record.max_x_mm) // 2,
                (record.min_y_mm + record.max_y_mm) // 2,
            )
            label = labels.get(record.part_key, "")
            slots.append(
                _slot(
                    record.identity,
                    record.part_key,
                    record.look_family,
                    record.look_leaf,
                    (middle[0], middle[1], 0),
                    {"north": 0, "west": 1, "south": 2, "east": 3}[record.door_facing],
                    (width, depth, height)
                    if record.door_facing in ("north", "south")
                    else (depth, width, height),
                    "none",
                    label=label,
                )
            )
            span = min(width, depth)
            rise = (
                ROOF_SLAB_MM
                if record.roof_form == "flat"
                else span * GABLE_RISE_NUMERATOR // GABLE_RISE_DENOMINATOR
            )
            ridge_along_y = depth >= width
            slots.append(
                _slot(
                    f"{record.identity}:roof",
                    record.part_key,
                    record.roof_family,
                    record.roof_leaf,
                    (middle[0], middle[1], height),
                    0 if ridge_along_y else 1,
                    (width, depth, rise) if ridge_along_y else (depth, width, rise),
                    "box" if record.roof_form == "flat" else "gable",
                    uv={
                        "originMm": [record.min_x_mm, record.min_y_mm, height],
                        "uAxisMm": [_UNIT, 0, 0],
                        "vAxisMm": [0, _UNIT, 0],
                    },
                    label=label,
                )
            )
        elif isinstance(record, SiteWallRecord):
            made, solid = _wall_slots(record, labels.get(record.part_key, ""))
            slots.extend(made)
            blocks.extend(solid)
        elif isinstance(record, SiteFixtureRecord):
            slots.append(
                _slot(
                    record.identity,
                    record.part_key,
                    record.look_family,
                    record.look_leaf,
                    (record.x_mm, record.y_mm, 0),
                    record.yaw_quarter_turns,
                    (record.width_mm, record.depth_mm, record.height_mm),
                    "box",
                    label=labels.get(record.part_key, ""),
                )
            )
            if record.blocks:
                along_x, along_y = (
                    (record.width_mm, record.depth_mm)
                    if record.yaw_quarter_turns % 2 == 0
                    else (record.depth_mm, record.width_mm)
                )
                blocks.append(
                    [
                        record.x_mm - along_x // 2,
                        record.y_mm - along_y // 2,
                        record.x_mm - along_x // 2 + along_x,
                        record.y_mm - along_y // 2 + along_y,
                    ]
                )
            if record.seats:
                seats.append(
                    {
                        "identity": record.identity,
                        "seatHeightMm": min(SEAT_HEIGHT_MAXIMUM_MM, record.height_mm // 2),
                    }
                )
    _state_structures(slots, records)
    arrival = receipt["arrival"]
    return {
        "profile": DRAWING_PROFILE,
        "world_id": world_id,
        "receipt_sha256": receipt_sha256,
        "kind": {
            "kind": receipt["kind"]["kind"],
            "version": receipt["kind"]["version"],
            "label": receipt["kind"]["document"]["label"],
        },
        "frame": {
            "name": "site_local",
            "unit": "millimetre",
            "axes": "x east, y north, z up, from the site's south-west corner",
            "region": "the region's east is x and its south is minus y",
        },
        "extent": {
            "widthMm": extent.width_mm,
            "depthMm": extent.depth_mm,
            "enclosure": extent.enclosure,
        },
        "arrival": {
            "positionMm": [arrival["position_mm"][0], arrival["position_mm"][1], 0],
            "facingMm": list(arrival["facing_mm"]),
        },
        "slots": slots,
        "walk": {
            "floorMm": [0, 0, extent.width_mm, extent.depth_mm],
            "blockersMm": blocks,
            "keepOutMm": keep_out,
        },
        "seats": seats,
    }


def _state_structures(slots: list[dict[str, Any]], records: Sequence[object]) -> None:
    """Say, on every slot that is a piece of a building, which building: its walls, lintels and
    doors, its roof, its rooms' floors and the fixtures in its rooms state ``structure``, the
    identity of the building's own slot. A pack that fills that slot with one piece for the whole
    building can then hide or show the building's own pieces together. A slot that belongs to no
    building (a boundary's wall, a fixture in a zone, the building's own slot) states none."""
    structures = {r.identity for r in records if isinstance(r, SiteStructureRecord)}
    rooms = {r.identity: r.structure_identity for r in records if isinstance(r, SiteRoomRecord)}
    owners: dict[str, str] = dict(rooms)
    for record in records:
        if isinstance(record, SiteWallRecord | SiteFixtureRecord):
            owner = rooms.get(record.owner_identity, record.owner_identity)
            if owner in structures:
                owners[record.identity] = owner
    for slot in slots:
        record_identity, _, piece = str(slot["identity"]).partition(":")
        structure = record_identity if piece and record_identity in structures else None
        structure = owners.get(record_identity, structure)
        if structure is not None:
            slot["structure"] = structure


def site_drawing_sha256(drawing: Mapping[str, Any]) -> str:
    """The SHA-256 of a drawing's canonical JSON: the digest it is served under."""
    return sha256_of_canonical(dict(drawing)).hex()
