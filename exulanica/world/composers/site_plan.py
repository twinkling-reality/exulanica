"""A world generated from a world kind by the site grammar: any kind of world but the town.

The composer for worlds made from a world kind (:mod:`exulanica.world.kinds`). A kind is not a
recipe of the recipe catalog, so :func:`compose` refuses a recipe by name; a world of a kind is
made by :func:`compose_kind`, from the kind, a person's values and the world's own identity,
trying the kind's seed candidates in order and keeping the first whose site is laid out and meets
every need its society has (:func:`~exulanica.world.kinds.samples.compose_site`). It states the
world it made as a structural snapshot and a receipt:

* **One region**, :data:`REGION_ID` (the one region every generated world states), whose frame is
  the site's own: the region origin is the site's south-west corner, east is the site's ``x`` and
  south its negative ``y``. The whole site is one element of the region, :data:`ELEMENT_ID`,
  placed at the origin, colliding with nothing the structure states: what a person walks on is
  the site's own records, served as its drawing (:mod:`exulanica.world.site_drawing`).
* **The receipt** carries the world kind's whole document, so a world regenerates from its receipt
  alone and no change to a kind's library entry moves it; the values; the site grammar and its
  descriptor digest; the kind catalogs' digests; the routine the society lives under (the town
  routine's binding and the kind's overlay); what each part is for; the candidate kept and each
  earlier refusal; the seed; the subject identity; the generation's output digest; and where a
  person arrives. The element's streaming key names the receipt's digest, so the snapshot binds it.
* **Where a person arrives**: on the spine, :data:`ARRIVAL_INSIDE_MM` in from the entry, facing
  into the site.

A receipt whose kind document, catalogs or grammar no longer read the same, or whose records come
out otherwise, is refused by name (``generated_world_*``), never generated into something else.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Final

from exulanica.grammar.grammars.site import (
    SITE_DESCRIPTOR_PATH,
    SITE_GRAMMAR_ID,
    SITE_GRAMMAR_VERSION,
    generate_site,
    site_records,
)
from exulanica.grammar.grammars.site.plan import plan_sha256
from exulanica.grammar.grammars.site.records import SiteExtentRecord, SitePathRecord
from exulanica.world.composers import (
    RECEIPT_PROFILE,
    ComposedWorld,
    StatedExtent,
    UnknownWorldComposer,
    receipt_sha256,
)
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.kinds.catalogs import load_kind_catalogs
from exulanica.world.kinds.document import KindDocument, KindRefused, read_kind
from exulanica.world.kinds.routine import kind_overlay, overlay_routine
from exulanica.world.kinds.samples import SiteWorld, compose_site
from exulanica.world.society_catalogs import RoutineModel
from exulanica.world.society_site_place import (
    CAPSULE_RADIUS_MM,
    SiteSociety,
    place_from_site_records,
)
from exulanica.world.starter import _EMPTY_GRAPH_SHA256, _EMPTY_RECONSTRUCTION_SHA256
from exulanica.world.structure import SpatialCandidate

__all__ = [
    "ARRIVAL_INSIDE_MM",
    "COMPOSER_KEY",
    "COMPOSER_VERSIONS",
    "DESTINATION_ID",
    "ELEMENT_ID",
    "REGION_ID",
    "SITE_MODULE",
    "compose",
    "compose_kind",
    "receipt_digest_of",
    "receipt_kind",
    "receipt_routine",
    "records",
    "society_place",
    "stated_extent",
    "tile_inputs",
]

COMPOSER_KEY: Final = "site-plan"
COMPOSER_VERSIONS: Final = (1,)
REGION_ID: Final = "region:generated"
DESTINATION_ID: Final = "destination:region:generated"
ELEMENT_ID: Final = "element:site"
#: The module a site's one element names: drawn from its site drawing, walked by its records.
SITE_MODULE: Final = "region.generated-site"
SITE_MODULE_VERSION: Final = 1
_STREAMING_KEY: Final = re.compile(r"site:([0-9a-f]{64})")
#: How a site's element states the site's extent: its width and depth in millimetres.
_SLOT_KEY: Final = re.compile(r"site:([1-9][0-9]{0,8}):([1-9][0-9]{0,8})")
#: How far in from the entry a person arrives, on the spine: past the 2,000 mm a town's arrival
#: keeps from where residents start (the town arrival policy's), so a person arriving never stands
#: on the off-site home people leave the site for.
ARRIVAL_INSIDE_MM: Final = 4_000
#: The steepest walking slope a structural snapshot states, as every snapshot the product writes.
MAXIMUM_SLOPE_MILLIDEGREES: Final = 15_000


def compose(recipe: object, world_id: str) -> ComposedWorld:
    """No recipe names this composer: a site world is made from a world kind
    (:func:`compose_kind`)."""
    raise UnknownWorldComposer(f"{COMPOSER_KEY} composes worlds from a world kind, not a recipe")


def _descriptor_sha256() -> str:
    return hashlib.sha256(SITE_DESCRIPTOR_PATH.read_bytes()).hexdigest()


def _arrival(world: SiteWorld) -> dict[str, Any]:
    extent = next(r for r in world.records if isinstance(r, SiteExtentRecord))
    spine = min(
        (r for r in world.records if isinstance(r, SitePathRecord)), key=lambda r: r.ordinal
    )
    y = min(spine.min_y_mm + ARRIVAL_INSIDE_MM, spine.max_y_mm - CAPSULE_RADIUS_MM)
    return {"position_mm": [extent.entry_x_mm, y], "facing_mm": [0, 1]}


def _candidate(
    kind: KindDocument,
    world_id: str,
    digest: str,
    arrival: Mapping[str, Any],
    extent: SiteExtentRecord,
) -> SpatialCandidate:
    east, north = arrival["position_mm"]
    topology = {
        "schema_version": 1,
        "world_id": world_id,
        "regions": [{"region_id": REGION_ID}],
        "elements": [
            {
                "element_id": ELEMENT_ID,
                "owner": {"kind": "region", "id": REGION_ID},
                "module": {
                    "key": SITE_MODULE,
                    "version": SITE_MODULE_VERSION,
                    "requested_key": SITE_MODULE,
                },
                "lineage": {
                    "recipe_key": kind.kind,
                    "recipe_version": kind.version,
                    "slot_key": f"site:{extent.width_mm}:{extent.depth_mm}",
                },
                "collision": {"kind": "none"},
                "evidence": {"kind": "none"},
                "attachment": None,
                "streaming_key": f"site:{digest}",
            }
        ],
        "navigation": {
            "agent_radius_mm": CAPSULE_RADIUS_MM,
            "maximum_slope_millidegrees": MAXIMUM_SLOPE_MILLIDEGREES,
            "destinations": [
                {"destination_id": DESTINATION_ID, "region_id": REGION_ID, "required": True}
            ],
            "edges": [],
        },
        "dependencies": [],
    }
    placement = {
        "schema_version": 1,
        "coordinate_unit": "millimetre",
        "elements": [
            {
                "element_id": ELEMENT_ID,
                "x_mm": 0,
                "y_mm": 0,
                "z_mm": 0,
                "yaw_microradians": 0,
                "scale_milli": 1_000,
            }
        ],
        "destinations": [
            {"destination_id": DESTINATION_ID, "x_mm": east, "y_mm": 0, "z_mm": -north}
        ],
    }
    return SpatialCandidate(
        _EMPTY_GRAPH_SHA256,
        _EMPTY_RECONSTRUCTION_SHA256,
        topology,
        {
            "schema_version": 1,
            "layout_version": 1,
            "regions": [{"region_id": REGION_ID, "creation_ordinal": 0}],
        },
        placement,
        {
            "schema_version": 1,
            "neighborhood_version": 1,
            "layout_version": 1,
            "neighborhoods": [
                {"neighborhood_id": "neighborhood:generated", "region_ids": [REGION_ID]}
            ],
        },
        composer_key=COMPOSER_KEY,
        composer_version=COMPOSER_VERSIONS[-1],
    )


def compose_kind(
    kind: KindDocument,
    values: Mapping[str, int],
    world_id: str,
    *,
    base_routine: RoutineModel | None = None,
) -> ComposedWorld:
    """The world ``kind`` makes with ``values`` for ``world_id``: its receipt, its structural
    candidate and its records. Refused as :func:`~exulanica.world.kinds.samples.compose_site`
    refuses (:class:`~exulanica.world.kinds.samples.SiteRefused`, every candidate named)."""
    if base_routine is None:
        from exulanica.world.society_living import town_routine

        base_routine = town_routine()
    overlay = kind_overlay(kind)
    routine = overlay_routine(base_routine, overlay)
    world = compose_site(kind, values, world_id, routine=routine)
    arrival = _arrival(world)
    receipt = {
        "profile": RECEIPT_PROFILE,
        "world_id": world_id,
        "kind": {**kind.reference(), "document": dict(kind.document)},
        "values": dict(sorted(values.items())),
        "composer": {"key": COMPOSER_KEY, "version": COMPOSER_VERSIONS[-1]},
        "grammar": {
            "grammar_id": SITE_GRAMMAR_ID,
            "grammar_version": SITE_GRAMMAR_VERSION,
            "descriptor_sha256": _descriptor_sha256(),
        },
        "catalogs": dict(load_kind_catalogs().sha256),
        "plan_sha256": world.plan_sha256,
        "routine": {"base": base_routine.binding(), "overlay": overlay, "sha256": routine.sha256},
        "society": world.society.document(),
        "candidate": world.candidate,
        "refused_candidates": [dict(refusal) for refusal in world.refused],
        "seed": world.seed,
        "subject_identity": world.subject_identity,
        "output_digest": world.output_digest,
        "record_count": len(world.records),
        "arrival": arrival,
    }
    digest = receipt_sha256(receipt)
    return ComposedWorld(
        receipt=receipt,
        receipt_sha256=digest,
        candidate=_candidate(
            kind,
            world_id,
            digest,
            arrival,
            next(r for r in world.records if isinstance(r, SiteExtentRecord)),
        ),
        records=world.records,
    )


def _check_current(receipt: Mapping[str, Any]) -> None:
    composer = receipt.get("composer", {})
    if composer.get("key") != COMPOSER_KEY or composer.get("version") not in COMPOSER_VERSIONS:
        raise InvalidStructuralData(
            "generated_world_composer_changed: unknown site composer version"
        )
    grammar = receipt["grammar"]
    if (grammar["grammar_id"], grammar["grammar_version"]) != (
        SITE_GRAMMAR_ID,
        SITE_GRAMMAR_VERSION,
    ) or grammar["descriptor_sha256"] != _descriptor_sha256():
        raise InvalidStructuralData(
            "generated_world_grammar_changed: this world was generated under a site grammar this "
            "server does not generate"
        )
    if receipt["catalogs"] != dict(load_kind_catalogs().sha256):
        raise InvalidStructuralData(
            "generated_world_catalogs_changed: this world was generated under world kind catalogs "
            "this server no longer holds"
        )


def receipt_kind(receipt: Mapping[str, Any]) -> KindDocument:
    """The world kind a receipt carries, read again and held to the digest the receipt names."""
    stated = receipt["kind"]
    document = {key: value for key, value in stated["document"].items()}
    try:
        kind = read_kind(document)
    except KindRefused as exc:
        raise InvalidStructuralData(
            f"generated_world_unreadable: its kind is refused: {exc}"
        ) from exc
    if kind.sha256 != stated["sha256"]:
        raise InvalidStructuralData("generated_world_unreadable: its kind reads to another digest")
    return kind


def receipt_routine(receipt: Mapping[str, Any]) -> RoutineModel:
    """The routine a receipt's world lives under: the town routine its binding names, with the
    kind's overlay, held to the digest the receipt records."""
    from exulanica.world.society_catalogs import ROUTINE_DIRECTORY, load_routine_model

    stated = receipt["routine"]
    base = load_routine_model(
        ROUTINE_DIRECTORY,
        versions={str(k): int(v) for k, v in stated["base"]["catalog_versions"].items()},
    )
    if base.binding() != stated["base"]:
        raise InvalidStructuralData(
            "generated_world_catalogs_changed: its routine catalogs changed"
        )
    routine = overlay_routine(base, stated["overlay"])
    if routine.sha256 != stated["sha256"]:
        raise InvalidStructuralData("generated_world_catalogs_changed: its routine reads otherwise")
    return routine


def records(receipt: Mapping[str, Any]) -> tuple[object, ...]:
    """The records a stored receipt generates again, held to its plan and output digests."""
    _check_current(receipt)
    kind = receipt_kind(receipt)
    plan = kind.plan(receipt["values"])
    if plan_sha256(plan) != receipt["plan_sha256"]:
        raise InvalidStructuralData(
            "generated_world_output_changed: its kind and values resolve to another plan"
        )
    generation = generate_site(
        plan, seed=receipt["seed"], subject_identity=receipt["subject_identity"]
    )
    if generation.receipt.output_digest != receipt["output_digest"]:
        raise InvalidStructuralData(
            "generated_world_output_changed: generating this world's receipt again produced "
            "other records"
        )
    return site_records(generation)


def society_place(
    place_id: str, receipt: Mapping[str, Any], generated: tuple[object, ...]
) -> dict[str, Any]:
    """The place a receipt's world hands its society, under the routine the receipt names."""
    return place_from_site_records(
        place_id=place_id,
        records=generated,
        society=SiteSociety.read(receipt["society"]),
        routine=receipt_routine(receipt),
    )


def receipt_digest_of(topology: Mapping[str, Any]) -> str:
    """The receipt a site world's snapshot names, read from its one element's streaming key."""
    elements = list(topology.get("elements", ()))
    if len(elements) != 1:
        raise InvalidStructuralData("a site world states one element")
    element = elements[0]
    found = _STREAMING_KEY.fullmatch(str(element.get("streaming_key", "")))
    if found is None or element.get("module", {}).get("key") != SITE_MODULE:
        raise InvalidStructuralData(
            f"a site world's element {element.get('element_id')!r} names no receipt"
        )
    return found.group(1)


def stated_extent(topology: Mapping[str, Any], placement: Mapping[str, Any]) -> StatedExtent:
    """The region, the rectangle the site covers in the region's frame (east 0 to its width, south
    minus its depth to 0) and the spawn, read from the snapshot: its one element names the receipt
    and states the site's width and depth in its slot key."""
    receipt_digest_of(topology)
    sized = _SLOT_KEY.fullmatch(str(topology["elements"][0]["lineage"]["slot_key"]))
    if sized is None:
        raise InvalidStructuralData("a site world's element states the site's width and depth")
    width, depth = int(sized.group(1)), int(sized.group(2))
    regions = tuple(str(region["region_id"]) for region in topology.get("regions", ()))
    if regions != (REGION_ID,):
        raise InvalidStructuralData(f"a site world states the one region {REGION_ID}")
    placed = {element["element_id"]: element for element in placement.get("elements", ())}
    where = placed.get(ELEMENT_ID)
    if where is None or (where["x_mm"], where["y_mm"], where["z_mm"]) != (0, 0, 0):
        raise InvalidStructuralData("a site world's element is placed at its region's origin")
    destinations = placement.get("destinations", ())
    if [d.get("destination_id") for d in destinations] != [DESTINATION_ID]:
        raise InvalidStructuralData(f"a site world states its spawn as {DESTINATION_ID}")
    spawn = destinations[0]
    return StatedExtent(
        region_id=REGION_ID,
        region_ids=regions,
        east_mm=(0, width),
        south_mm=(-depth, 0),
        arrival_mm=(spawn["x_mm"], spawn["y_mm"], spawn["z_mm"]),
    )


def tile_inputs(receipt: Mapping[str, Any]) -> tuple[tuple[tuple[int, int], str], ...]:
    """A site world is drawn from its records, not baked: it has no tiles."""
    return ()
