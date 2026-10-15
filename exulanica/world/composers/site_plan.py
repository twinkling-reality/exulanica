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
  descriptor digest; the kind catalogs' digests, as a record of what it was checked against (a
  catalog edit that leaves its plan and records as they were does not unmake the world: the plan
  and output digests are what hold it); the routine the society lives under (the town
  routine's binding and the kind's overlay); what each part is for; the candidate kept and each
  earlier refusal; the seed; the subject identity; the generation's output digest; and where a
  person arrives. The element's streaming key names the receipt's digest, so the snapshot binds it.
* **Where a person arrives**: on the spine, :data:`ARRIVAL_INSIDE_MM` in from the entry, facing
  into the site.

A receipt whose kind document, routine catalogs or grammar no longer read the same, or whose records
come out otherwise, is refused by name (``generated_world_*``), never generated into something else.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, Final

from exulanica.grammar.errors import InvalidParameterError
from exulanica.grammar.grammars.site import (
    SITE_DESCRIPTOR_PATH,
    SITE_GRAMMAR_ID,
    SITE_GRAMMAR_VERSION,
    generate_site,
    site_records,
)
from exulanica.grammar.grammars.site.layout import LayoutOverBudget
from exulanica.grammar.grammars.site.plan import plan_sha256
from exulanica.grammar.grammars.site.records import SiteExtentRecord, SitePathRecord
from exulanica.grammar.landform import LandformRefused, land_rules, read_land_document
from exulanica.world.composers import (
    RECEIPT_PROFILE,
    ComposedWorld,
    StatedExtent,
    UnknownWorldComposer,
    receipt_sha256,
)
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.kinds.catalogs import load_arcade_catalog, load_kind_catalogs
from exulanica.world.kinds.document import (
    KindDocument,
    KindRefused,
    bounds_version_of,
    read_kind,
)
from exulanica.world.kinds.routine import kind_overlay, overlay_routine
from exulanica.world.kinds.samples import SiteWorld, compose_site, layout_budget
from exulanica.world.site_land import SiteLand, check_receipt_land_rules, site_land_of
from exulanica.world.society_catalogs import RoutineModel
from exulanica.world.society_site_place import (
    CAPSULE_RADIUS_MM,
    SiteSociety,
    place_from_site_records,
)
from exulanica.world.starter import _EMPTY_GRAPH_SHA256, _EMPTY_RECONSTRUCTION_SHA256
from exulanica.world.structure import SpatialCandidate
from exulanica.world.terrain_authoring import TERRAIN_COMPOSER_VERSIONS

__all__ = [
    "ARRIVAL_INSIDE_MM",
    "COMPOSER_KEY",
    "COMPOSER_VERSIONS",
    "DESTINATION_ID",
    "ELEMENT_ID",
    "LAND_COMPOSER_VERSION",
    "REGION_ID",
    "SITE_MODULE",
    "check_receipt",
    "compose",
    "compose_kind",
    "receipt_digest_of",
    "receipt_kind",
    "receipt_land",
    "receipt_routine",
    "records",
    "society_place",
    "stated_extent",
    "tile_inputs",
]

COMPOSER_KEY: Final = "site-plan"
#: The composer version of a site laid out on land: its receipt carries the land document and
#: names the land rules that made its land.
LAND_COMPOSER_VERSION: Final = 5
COMPOSER_VERSIONS: Final = (1, 2, *TERRAIN_COMPOSER_VERSIONS, LAND_COMPOSER_VERSION)
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
    *,
    composer_version: int = 1,
    up_mm: int = 0,
) -> SpatialCandidate:
    east, north = arrival["position_mm"]
    return _site_candidate(
        kind.kind,
        kind.version,
        world_id,
        digest,
        (east, up_mm, -north),
        extent.width_mm,
        extent.depth_mm,
        composer_version=composer_version,
    )


def _site_candidate(
    recipe_key: str,
    recipe_version: int,
    world_id: str,
    digest: str,
    arrival: tuple[int, int, int],
    width: int,
    depth: int,
    *,
    composer_version: int,
) -> SpatialCandidate:
    east, up, south = arrival
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
                    "recipe_key": recipe_key,
                    "recipe_version": recipe_version,
                    "slot_key": f"site:{width}:{depth}",
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
            {"destination_id": DESTINATION_ID, "x_mm": east, "y_mm": up, "z_mm": south}
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
        composer_version=composer_version,
    )


def compose_terrain(authoring: dict, world_id: str) -> ComposedWorld:
    """Compose an admitted terrain source without a flat kind or society claim."""
    from exulanica.world.terrain_authoring import read_terrain_authoring

    source = read_terrain_authoring(authoring)
    receipt = {
        "profile": RECEIPT_PROFILE,
        "world_id": world_id,
        "composer": {"key": COMPOSER_KEY, "version": source.composer_version},
        "authoring": source.document(),
        "authoring_sha256": source.sha256,
        "arrival": source.arrival(),
        "output_digest": source.sha256,
        "record_count": 1,
    }
    sha = receipt_sha256(receipt)
    geometry = source.contact.geometry
    candidate = _site_candidate(
        "terrain.authoring",
        1,
        world_id,
        sha,
        tuple(source.arrival()["position_mm"]),
        geometry.east_mm[-1],
        -geometry.south_mm[0],
        composer_version=source.composer_version,
    )
    return ComposedWorld(receipt, sha, candidate, (source,))


def receipt_terrain(receipt: Mapping[str, Any]) -> Any:
    """Revalidate the complete retained source and exact arrival on cold replay."""
    from exulanica.world.terrain_authoring import TerrainAuthoringRefused, read_terrain_authoring

    expected = {
        "profile",
        "world_id",
        "composer",
        "authoring",
        "authoring_sha256",
        "arrival",
        "output_digest",
        "record_count",
    }
    try:
        if (
            set(receipt) != expected
            or receipt["profile"] != RECEIPT_PROFILE
            or receipt["composer"]
            not in [
                {"key": COMPOSER_KEY, "version": version} for version in TERRAIN_COMPOSER_VERSIONS
            ]
            or type(receipt["record_count"]) is not int
            or receipt["record_count"] != 1
        ):
            raise ValueError("invalid terrain receipt fields")
        source = read_terrain_authoring(receipt["authoring"])
        if (
            source.composer_version != receipt["composer"]["version"]
            or source.sha256 != receipt["authoring_sha256"]
            or source.sha256 != receipt["output_digest"]
            or source.arrival() != receipt["arrival"]
        ):
            raise ValueError("terrain source or arrival binding differs")
        return source
    except (TerrainAuthoringRefused, ValueError, TypeError, KeyError) as exc:
        raise InvalidStructuralData(f"generated_world_terrain_changed: {exc}") from exc


def compose_kind(
    kind: KindDocument,
    values: Mapping[str, int],
    world_id: str,
    *,
    base_routine: RoutineModel | None = None,
    place_id: str | None = None,
    support: Mapping[str, Any] | None = None,
    land: Mapping[str, Any] | None = None,
) -> ComposedWorld:
    """The world ``kind`` makes with ``values`` for ``world_id``: its receipt, its structural
    candidate and its records, and with ``place_id`` the place its society walks there, the one its
    checks built (:func:`society_place` makes the same from the receipt). With ``land`` (an
    ``exulanica.landform/v1`` document) the site is laid out on that land as composer version
    :data:`LAND_COMPOSER_VERSION`: its receipt carries the land document and its digest and names
    the land rules that made its land (:func:`~exulanica.grammar.landform.land_rules`), its
    candidates are graded (:mod:`exulanica.world.site_land`) and a person arrives at the land's
    height; the document is refused as :class:`~exulanica.grammar.landform.LandformRefused`, and
    land with a support declaration is not served. Refused as
    :func:`~exulanica.world.kinds.samples.compose_site` refuses
    (:class:`~exulanica.world.kinds.samples.SiteRefused`, every candidate named)."""
    if base_routine is None:
        from exulanica.world.society_living import town_routine

        base_routine = town_routine()
    overlay = kind_overlay(kind)
    routine = overlay_routine(base_routine, overlay)
    document = None
    if land is not None:
        if support is not None:
            raise LandformRefused(
                "a site is laid out on land or on a support declaration, not both",
                path="land",
                code="landform_not_served",
            )
        document = read_land_document(land)
    world = compose_site(kind, values, world_id, routine=routine, land=document)
    arrival = _arrival(world)
    receipt = {
        "profile": RECEIPT_PROFILE,
        "world_id": world_id,
        "kind": {**kind.reference(), "document": dict(kind.document)},
        "values": dict(sorted(values.items())),
        "composer": {"key": COMPOSER_KEY, "version": 1},
        "grammar": {
            "grammar_id": SITE_GRAMMAR_ID,
            "grammar_version": SITE_GRAMMAR_VERSION,
            "descriptor_sha256": _descriptor_sha256(),
        },
        "catalogs": dict(
            load_kind_catalogs(bounds_version=bounds_version_of(kind.document)).sha256
        ),
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
    if kind.arcaded:
        # Named only for a kind that reads it, so a world without an arcade names what it did.
        receipt["catalogs"]["structure-arcade"] = load_arcade_catalog().sha256
    supported_place = world.place
    composer_version = 1
    up_mm = 0
    if document is not None:
        receipt["land"] = document.canonical()
        receipt["land_sha256"] = document.sha256
        receipt["land_rules"] = land_rules()
        receipt["composer"]["version"] = LAND_COMPOSER_VERSION
        composer_version = LAND_COMPOSER_VERSION
        graded = site_land_of(receipt, world.records, routine.policy["footway_station_spacing_mm"])
        up_mm = graded.height_at(*arrival["position_mm"])
    if support is not None:
        from exulanica.world.site_drawing import _site_drawing_v1
        from exulanica.world.support_site import BASE_SURFACE, attach_site_support

        source_place = _placed_at(world.place, _support_place_id())
        attached = attach_site_support(
            support,
            world_id=world_id,
            records=world.records,
            drawing=_site_drawing_v1(
                world_id=world_id,
                receipt=receipt,
                receipt_sha256=receipt_sha256(receipt),
                records=world.records,
            ),
            base_place=source_place,
            routine=routine,
        )
        east, north = arrival["position_mm"]
        attached.network.support_at(BASE_SURFACE, (east, -north))
        receipt["supports"] = attached.document()
        composer_version = 2
        receipt["composer"]["version"] = 2
        supported_place = attached.projection.place()
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
            composer_version=composer_version,
            up_mm=up_mm,
        ),
        records=world.records,
        place=None if place_id is None else _placed_at(supported_place, place_id),
    )


def _placed_at(place: Mapping[str, Any], place_id: str) -> dict[str, Any]:
    """A place a check built under another identity, as the place ``place_id`` names: the place
    names its identity once, so it is the same document sealed again."""
    from exulanica.world.society_place import seal_place

    stated = {key: value for key, value in place.items() if key != "document_sha256"}
    return seal_place({**stated, "place_id": place_id})


def _support_place_id() -> str:
    from exulanica.world.society_authored_ground import ground_place_id

    return ground_place_id(REGION_ID)


def receipt_support(receipt: Mapping[str, Any], generated: tuple[object, ...]) -> Any:
    """Reconcile persisted supports against actual regenerated geometry and its base routine."""
    from exulanica.world.site_drawing import _site_drawing_v1
    from exulanica.world.support_site import read_site_support
    from exulanica.world.support_surfaces import SupportRefused

    try:
        base = place_from_site_records(
            place_id=_support_place_id(),
            records=generated,
            society=SiteSociety.read(receipt["society"]),
            routine=receipt_routine(receipt),
            node_limit=load_kind_catalogs().bound("walking_nodes")[1],
        )
        return read_site_support(
            receipt["supports"],
            world_id=receipt["world_id"],
            records=generated,
            drawing=_site_drawing_v1(
                world_id=receipt["world_id"],
                receipt=receipt,
                receipt_sha256=receipt_sha256(receipt),
                records=generated,
            ),
            base_place=base,
            routine=receipt_routine(receipt),
        )
    except (SupportRefused, KeyError, TypeError, ValueError) as exc:
        raise InvalidStructuralData(
            "generated_world_support_changed: support binding no longer reconciles"
        ) from exc


def check_receipt(receipt: Mapping[str, Any]) -> None:
    """Refuse by name a stored receipt this server no longer makes its world from, by the checks
    that generate nothing: its composer, its support and land bindings, the land rules it names and
    the site grammar's descriptor. Generating a receipt's records again runs these first, and a
    saved world's entry is listed by them, so a world listed available is one these let open."""
    composer = receipt.get("composer", {})
    if composer.get("key") != COMPOSER_KEY or composer.get("version") not in COMPOSER_VERSIONS:
        raise InvalidStructuralData(
            "generated_world_composer_changed: unknown site composer version"
        )
    if composer["version"] in TERRAIN_COMPOSER_VERSIONS:
        receipt_terrain(receipt)
        return
    if (composer["version"] == 2) != ("supports" in receipt):
        raise InvalidStructuralData(
            "generated_world_support_changed: composer/support binding mismatch"
        )
    if (composer["version"] == LAND_COMPOSER_VERSION) != ("land" in receipt):
        raise InvalidStructuralData("generated_world_land_changed: composer/land binding mismatch")
    if composer["version"] == LAND_COMPOSER_VERSION:
        check_receipt_land_rules(receipt)
    elif "land_rules" in receipt:
        raise InvalidStructuralData(
            "generated_world_land_rules_changed: composer/land rules binding mismatch"
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


def receipt_kind(receipt: Mapping[str, Any]) -> KindDocument:
    """The world kind a receipt carries, read again and held to the digest the receipt names."""
    if receipt.get("composer", {}).get("version") in TERRAIN_COMPOSER_VERSIONS:
        raise InvalidStructuralData("terrain_world_kind_unavailable")
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
    kind's overlay, held to the digest the receipt records. Read once per binding: the catalogs it
    names are read from disk the first time only."""
    if receipt.get("composer", {}).get("version") in TERRAIN_COMPOSER_VERSIONS:
        raise InvalidStructuralData("terrain_society_projection_unavailable")
    return _routine_of(json.dumps(receipt["routine"], sort_keys=True, separators=(",", ":")))


@functools.lru_cache(maxsize=32)
def _routine_of(binding: str) -> RoutineModel:
    from exulanica.world.society_catalogs import ROUTINE_DIRECTORY, load_routine_model

    stated = json.loads(binding)
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
    """The records a stored receipt generates again, held to its plan and output digests, within
    the layout budget a world is made under (a world laid out within it then is within it again,
    unless the bounds catalog has since lowered it, which is refused by name)."""
    if receipt.get("composer", {}).get("version") in TERRAIN_COMPOSER_VERSIONS:
        return (receipt_terrain(receipt),)
    check_receipt(receipt)
    kind = receipt_kind(receipt)
    try:
        plan = kind.plan(receipt["values"])
    except InvalidParameterError as exc:
        raise InvalidStructuralData(
            f"generated_world_output_changed: its kind and values make no plan: {exc}"
        ) from exc
    if plan_sha256(plan) != receipt["plan_sha256"]:
        raise InvalidStructuralData(
            "generated_world_output_changed: its kind and values resolve to another plan"
        )
    try:
        generation = generate_site(
            plan,
            seed=receipt["seed"],
            subject_identity=receipt["subject_identity"],
            budget=layout_budget(),
        )
    except LayoutOverBudget as exc:
        raise InvalidStructuralData(
            "generated_world_catalogs_changed: laying it out again tries more placements than "
            f"the bounds catalog now allows ({exc})"
        ) from exc
    if generation.receipt.output_digest != receipt["output_digest"]:
        raise InvalidStructuralData(
            "generated_world_output_changed: generating this world's receipt again produced "
            "other records"
        )
    generated = site_records(generation)
    if receipt["composer"]["version"] == 2:
        receipt_support(receipt, generated)
    if receipt["composer"]["version"] == LAND_COMPOSER_VERSION:
        receipt_land(receipt, generated)
    return generated


def receipt_land(receipt: Mapping[str, Any], generated: tuple[object, ...]) -> SiteLand:
    """The graded land a version 5 receipt states for its regenerated records, or refused by name
    when its land no longer reads or no longer takes its layout."""
    try:
        return site_land_of(
            receipt, generated, receipt_routine(receipt).policy["footway_station_spacing_mm"]
        )
    except LandformRefused as exc:
        raise InvalidStructuralData(
            f"generated_world_land_changed: its land no longer takes its layout: {exc.detail}"
        ) from exc


def society_place(
    place_id: str, receipt: Mapping[str, Any], generated: tuple[object, ...]
) -> dict[str, Any]:
    """The place a receipt's world hands its society, under the routine the receipt names, its
    walking graph held to the bounds catalog's ``walking_nodes`` while it is built (refused as
    :class:`~exulanica.world.society_site_place.GraphOverBudget`), as a kind's checks hold it."""
    if receipt["composer"]["version"] in TERRAIN_COMPOSER_VERSIONS:
        receipt_terrain(receipt)
        raise InvalidStructuralData("terrain_society_projection_unavailable")
    if receipt["composer"]["version"] == 2:
        return _placed_at(receipt_support(receipt, generated).projection.place(), place_id)
    ground = None
    if receipt["composer"]["version"] == LAND_COMPOSER_VERSION:
        ground = receipt_land(receipt, generated).height_at
    return place_from_site_records(
        place_id=place_id,
        records=generated,
        society=SiteSociety.read(receipt["society"]),
        routine=receipt_routine(receipt),
        node_limit=load_kind_catalogs().bound("walking_nodes")[1],
        ground=ground,
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
