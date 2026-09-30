"""A world generated from the city grammar: its streets, buildings, premises and walking surfaces.

The composer for recipes that name ``city-grammar-town``. It generates the recipe's specification
through the one generation path (:mod:`exulanica.grammar.grammars.specified`), at the city grammar
version the specification names, trying the recipe's seed candidates in order and keeping the first
that generates, whose tile documents pass the grammar's own checks, and on which a society can
start: its homes hold at least one person and no more than the society ground stated for this
composer holds (``refuse_population`` in :mod:`exulanica.world.society_grounds`). It states the
world it made as a structural snapshot and a receipt:

* **One region**, :data:`REGION_ID`, whose frame is the city's own: the region origin is the
  city frame's origin, east is the city's ``x`` and south its negative ``y``, heights stay the
  records' own. Every tile the world covers is one element of the region, placed at its tile's
  south-west corner, drawn from its baked tile and colliding with nothing the structure states:
  what a person stands on is the walking surfaces the records state.
* **The receipt** (:data:`~exulanica.world.composers.RECEIPT_PROFILE`): the recipe, the
  specification, the grammar and its descriptor digest, the catalog digest, the candidate kept
  and each earlier candidate's refusal, the seed, the subject identity and the generation's
  output digest. Each element's streaming key names the receipt's SHA-256, so the snapshot's
  digest binds it, and :func:`records` generates the records again and holds them to the output
  digest, so a world's records are never stored twice or read from a copy.
* **Where a person arrives**, by one rule: the standing spot the city's walking surfaces offer
  nearest the centre of the world's extent, ties by spot identity. The snapshot states it as the
  region's destination, the world's own spawn, so every reader reads one point. A person arriving
  there faces the nearest point of any street's crown line, ties by street segment identity, so
  they look across the street rather than into a wall; the receipt records that facing as a plan
  vector, because a structural destination states a point and no direction.

The grammar and its catalogs are not edited here: a receipt names the grammar version and catalog
digest it was generated under, and a world whose grammar or catalogs no longer match is refused by
name rather than regenerated into something else.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any, Final

from exulanica.grammar.catalogs import Catalog, catalog_digest
from exulanica.grammar.errors import InvalidParameterError, InvalidRecordError
from exulanica.grammar.grammars.city.catalogs import load_city_catalogs
from exulanica.grammar.grammars.city.common import TILE_SIZE_MM
from exulanica.grammar.grammars.city.descriptor import (
    CITY_DESCRIPTOR_PATHS,
    CITY_GENERATING_VERSIONS,
    CITY_GRAMMAR_ID,
)
from exulanica.grammar.grammars.city.document import (
    TileDocument,
    descriptor_sha256,
    document_bytes,
    validate_city_document,
)
from exulanica.grammar.grammars.city.generation.tiles import (
    check_city_reference_closure,
    check_piece_lengths,
    city_records,
    tile_document,
    tile_record,
)
from exulanica.grammar.grammars.city.streets import StreetSegmentRecord
from exulanica.grammar.grammars.city.tile import tile_inputs_digest
from exulanica.grammar.grammars.specified import (
    GENERATED_LOD,
    covered_tiles,
    derived_identity,
    generate_specified,
)
from exulanica.world.composers import (
    RECEIPT_PROFILE,
    ComposedWorld,
    GeneratedWorldRefused,
    StatedExtent,
    UnknownWorldComposer,
    receipt_sha256,
    seed_candidate,
)
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.society_city_place import city_navigation
from exulanica.world.society_grounds import (
    SocietyPopulationRefused,
    refuse_population,
    society_ground_for_composer,
)
from exulanica.world.society_walking_surfaces import place_residents, walking_surfaces_place
from exulanica.world.starter import _EMPTY_GRAPH_SHA256, _EMPTY_RECONSTRUCTION_SHA256
from exulanica.world.structure import SpatialCandidate
from exulanica.world.world_recipes import WorldRecipe, read_specification

__all__ = [
    "COMPOSER_KEY",
    "COMPOSER_VERSIONS",
    "DESTINATION_ID",
    "GRAMMAR_VERSIONS",
    "REGION_ID",
    "TILE_MODULE",
    "compose",
    "receipt_digest_of",
    "records",
    "region_point",
    "stated_extent",
    "tile_documents",
    "tile_inputs",
]

COMPOSER_KEY: Final = "city-grammar-town"
COMPOSER_VERSIONS: Final = (1,)
#: The city grammar versions this composer generates: every version the city grammar itself
#: generates. Each version reads its own catalogs, tile records and descriptor, and this composer
#: reads them at the version a recipe names or a receipt records, so a world generated under
#: version 3 is read again under version 3 after later versions exist, and a recipe naming a version
#: the grammar does not generate is refused by name.
GRAMMAR_VERSIONS: Final = CITY_GENERATING_VERSIONS
REGION_ID: Final = "region:generated"
DESTINATION_ID: Final = "destination:region:generated"
#: The module a generated tile element names: drawn from its baked tile, walked by its records.
TILE_MODULE: Final = "region.generated-tile"
TILE_MODULE_VERSION: Final = 1
#: How a tile element's streaming key names the receipt and the tile: a prefix, the receipt's
#: SHA-256 and the tile's coordinate.
_STREAMING_KEY: Final = re.compile(r"generated:([0-9a-f]{64}):tile:(-?[0-9]+):(-?[0-9]+)")
#: The steepest walking slope a structural snapshot states, the figure every snapshot the product
#: writes states (the starter's and a composed world's). A recipe's terrain states its own relief;
#: this is the structure's statement, not the society's, which walks only the records' surfaces.
MAXIMUM_SLOPE_MILLIDEGREES: Final = 15_000
#: Longest refusal text a receipt keeps per candidate: the stage's own sentence, bounded so one
#: verbose refusal cannot grow a receipt without limit.
_REFUSAL_CHARACTERS: Final = 500


def region_point(x_mm: int, y_mm: int) -> tuple[int, int]:
    """A city frame point as the region states it: east, then south."""
    return x_mm, -y_mm


def _element_id(tile: Sequence[int]) -> str:
    return f"element:tile:{tile[0]:+05d}:{tile[1]:+05d}"


def _extent(tiles: Sequence[Sequence[int]]) -> tuple[int, int, int, int]:
    """The city frame rectangle the tiles cover: west, south, east and north edges."""
    xs = [tile[0] for tile in tiles]
    ys = [tile[1] for tile in tiles]
    return (
        min(xs) * TILE_SIZE_MM,
        min(ys) * TILE_SIZE_MM,
        (max(xs) + 1) * TILE_SIZE_MM,
        (max(ys) + 1) * TILE_SIZE_MM,
    )


def _arrival(place: Mapping[str, Any], tiles: Sequence[Sequence[int]]) -> Any:
    """The standing spot nearest the centre of the world's extent, as a spot of the place."""
    west, south, east, north = _extent(tiles)
    centre = ((west + east) // 2, (south + north) // 2)
    spots = place["spots"]
    if not spots:
        raise InvalidRecordError("the generated world's walking surfaces offer nowhere to stand")
    return min(
        spots,
        key=lambda spot: (
            (spot["position_mm"][0] - centre[0]) ** 2 + (spot["position_mm"][1] - centre[1]) ** 2,
            spot["spot_id"],
        ),
    )


def _facing(position: Sequence[int], generated: Sequence[object]) -> list[int]:
    """The plan vector from ``position`` to the nearest point of any street's crown line, in the
    city frame, found in integer arithmetic; ties by street segment identity."""
    best: tuple[tuple[int, str], tuple[int, int]] | None = None
    px, py = position[0], position[1]
    for record in generated:
        if not isinstance(record, StreetSegmentRecord):
            continue
        for (ax, ay, _), (bx, by, _) in pairwise(record.centreline_mm):
            dx, dy = bx - ax, by - ay
            length = dx * dx + dy * dy
            along = 0 if length == 0 else max(0, min(length, (px - ax) * dx + (py - ay) * dy))
            nearest = (
                (ax, ay) if length == 0 else (ax + dx * along // length, ay + dy * along // length)
            )
            key = ((nearest[0] - px) ** 2 + (nearest[1] - py) ** 2, record.identity)
            if best is None or key < best[0]:
                best = (key, nearest)
    if best is None:
        raise InvalidRecordError("the generated world states no street to face")
    return [best[1][0] - px, best[1][1] - py]


def _candidate(
    recipe: WorldRecipe, world_id: str, receipt: Mapping[str, Any], digest: str, arrival: Any
) -> SpatialCandidate:
    tiles = [tuple(tile) for tile in receipt["tiles"]]
    east, south = region_point(*arrival["position_mm"])
    radius = city_navigation().capsule_radius_mm
    topology = {
        "schema_version": 1,
        "world_id": world_id,
        "regions": [{"region_id": REGION_ID}],
        "elements": [
            {
                "element_id": _element_id(tile),
                "owner": {"kind": "region", "id": REGION_ID},
                "module": {
                    "key": TILE_MODULE,
                    "version": TILE_MODULE_VERSION,
                    "requested_key": TILE_MODULE,
                },
                "lineage": {
                    "recipe_key": recipe.key,
                    "recipe_version": recipe.catalog_version,
                    "slot_key": f"tile:{tile[0]}:{tile[1]}",
                },
                "collision": {"kind": "none"},
                "evidence": {"kind": "none"},
                "attachment": None,
                "streaming_key": f"generated:{digest}:tile:{tile[0]}:{tile[1]}",
            }
            for tile in sorted(tiles, key=_element_id)
        ],
        "navigation": {
            "agent_radius_mm": radius,
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
                "element_id": _element_id(tile),
                "x_mm": region_point(tile[0] * TILE_SIZE_MM, tile[1] * TILE_SIZE_MM)[0],
                "y_mm": 0,
                "z_mm": region_point(tile[0] * TILE_SIZE_MM, tile[1] * TILE_SIZE_MM)[1],
                "yaw_microradians": 0,
                "scale_milli": 1_000,
            }
            for tile in sorted(tiles, key=_element_id)
        ],
        "destinations": [
            {
                "destination_id": DESTINATION_ID,
                "x_mm": east,
                "y_mm": arrival["support_z_mm"],
                "z_mm": south,
            }
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
        composer_version=recipe.composer_version,
    )


def compose(recipe: WorldRecipe, world_id: str) -> ComposedWorld:
    """The world ``recipe`` makes for ``world_id``: the first seed candidate that generates.

    A candidate the grammar refuses (a stage that cannot build what its values ask, a range a
    stage narrows, or a tile document its own checks refuse), or whose homes hold nobody or more
    people than its society ground holds, is recorded with its own sentence and the next is tried;
    a recipe none of whose candidates generate is refused by name with every refusal.
    """
    if recipe.composer_key != COMPOSER_KEY or recipe.composer_version not in COMPOSER_VERSIONS:
        raise ValueError(f"recipe {recipe.key} is not composed by {COMPOSER_KEY}")
    spec = read_specification(recipe.specification)
    if spec.grammar.key.grammar_version not in GRAMMAR_VERSIONS:
        raise UnknownWorldComposer(
            f"{COMPOSER_KEY} generates city grammar version "
            f"{', '.join(map(str, GRAMMAR_VERSIONS))}, and recipe {recipe.key} names version "
            f"{spec.grammar.key.grammar_version}"
        )
    version = spec.grammar.key.grammar_version
    catalogs = load_city_catalogs(grammar_version=version)
    ground = society_ground_for_composer(COMPOSER_KEY)
    refused: list[dict[str, object]] = []
    for candidate in range(recipe.candidates):
        seed = seed_candidate(recipe, world_id, candidate)
        identity = derived_identity(seed)
        try:
            _, tiles = covered_tiles(spec, seed)
            generation = generate_specified(spec, seed=seed, subject_identity=identity)
            generated = city_records(generation)
            check_piece_lengths(generated)
            # A world is kept only if every tile document it makes passes the grammar's own
            # checks, so every world a recipe makes can be baked.
            _documents(seed, identity, generated, tiles, catalogs, version)
            place = walking_surfaces_place(f"generated:{world_id}", generated)
            arrival = _arrival(place, tiles)
            # A world is kept only if a society can start on it: someone lives there, and no more
            # people than one tick of a society over its ground was measured to hold.
            refuse_population(place_residents(place), ground)
        except (InvalidParameterError, InvalidRecordError) as exc:
            sentence = f"{type(exc).__name__}: {exc}"
            refused.append({"candidate": candidate, "refusal": sentence[:_REFUSAL_CHARACTERS]})
            continue
        except SocietyPopulationRefused as exc:
            sentence = f"{exc.code}: {exc.detail}"
            refused.append({"candidate": candidate, "refusal": sentence[:_REFUSAL_CHARACTERS]})
            continue
        if len(tiles) != len(recipe.tiles):
            raise InvalidStructuralData(
                f"recipe {recipe.key} states {len(recipe.tiles)} tiles and generated {len(tiles)}"
            )
        receipt = {
            "profile": RECEIPT_PROFILE,
            "world_id": world_id,
            "recipe": recipe.reference(),
            "composer": {"key": COMPOSER_KEY, "version": recipe.composer_version},
            "specification": spec.payload(),
            "grammar": {
                "grammar_id": spec.grammar.key.grammar_id,
                "grammar_version": spec.grammar.key.grammar_version,
                "descriptor_sha256": descriptor_sha256(CITY_DESCRIPTOR_PATHS[version]),
            },
            "catalog_digest": catalog_digest(catalogs),
            "candidate": candidate,
            "refused_candidates": refused,
            "seed": seed,
            "subject_identity": identity,
            "output_digest": generation.receipt.output_digest,
            "record_count": len(generated),
            "tiles": [list(tile) for tile in tiles],
            "arrival": {
                "spot_id": arrival["spot_id"],
                "position_mm": list(arrival["position_mm"]),
                "facing_mm": _facing(arrival["position_mm"], generated),
            },
        }
        digest = receipt_sha256(receipt)
        return ComposedWorld(
            receipt=receipt,
            receipt_sha256=digest,
            candidate=_candidate(recipe, world_id, receipt, digest, arrival),
            records=generated,
        )
    raise GeneratedWorldRefused(recipe.key, refused)


def receipt_digest_of(topology: Mapping[str, Any]) -> str:
    """The receipt a generated world's snapshot names, read from its tile elements' streaming keys.

    Every tile element names the same receipt; a snapshot whose elements name none, several, or a
    key of another shape is refused by name.
    """
    digests = set()
    for element in topology.get("elements", ()):
        found = _STREAMING_KEY.fullmatch(str(element.get("streaming_key", "")))
        if found is None or element.get("module", {}).get("key") != TILE_MODULE:
            raise InvalidStructuralData(
                f"a generated world's element {element.get('element_id')!r} names no receipt"
            )
        digests.add(found.group(1))
    if len(digests) != 1:
        raise InvalidStructuralData("a generated world's elements name one receipt, and only one")
    return digests.pop()


def _version(receipt: Mapping[str, Any]) -> int:
    """The city grammar version a receipt records, refused by name when this server generates none
    such, so a receipt is never read against another version's catalogs."""
    grammar = receipt["grammar"]
    version = grammar["grammar_version"]
    if grammar["grammar_id"] != CITY_GRAMMAR_ID or version not in GRAMMAR_VERSIONS:
        raise InvalidStructuralData(
            "generated_world_grammar_changed: this world was generated under city grammar "
            f"version {version}, which this server does not generate"
        )
    return int(version)


def _check_current(receipt: Mapping[str, Any], catalogs: Sequence[Catalog]) -> None:
    grammar = receipt["grammar"]
    if grammar["descriptor_sha256"] != descriptor_sha256(CITY_DESCRIPTOR_PATHS[_version(receipt)]):
        raise InvalidStructuralData(
            "generated_world_grammar_changed: this world was generated under city grammar "
            f"version {grammar['grammar_version']}, which this server does not generate"
        )
    if receipt["catalog_digest"] != catalog_digest(catalogs):
        raise InvalidStructuralData(
            "generated_world_catalogs_changed: this world was generated under city catalogs this "
            "server no longer holds"
        )


def records(receipt: Mapping[str, Any]) -> tuple[object, ...]:
    """The records a stored receipt generates again, held to its output digest."""
    catalogs = load_city_catalogs(grammar_version=_version(receipt))
    _check_current(receipt, catalogs)
    specification = receipt["specification"]
    spec = read_specification(
        {
            "grammar_id": specification["grammar_id"],
            "grammar_version": specification["grammar_version"],
            "bindings": specification["bindings"],
        }
    )
    generation = generate_specified(
        spec, seed=receipt["seed"], subject_identity=receipt["subject_identity"]
    )
    if generation.receipt.output_digest != receipt["output_digest"]:
        raise InvalidStructuralData(
            "generated_world_output_changed: generating this world's receipt again produced "
            "other records"
        )
    return city_records(generation)


def _documents(
    seed: str,
    identity: str,
    generated: Sequence[object],
    tiles: Sequence[Sequence[int]],
    catalogs: Sequence[Catalog],
    version: int,
) -> tuple[TileDocument, ...]:
    documents = []
    for tile_x, tile_y in tiles:
        document = tile_document(
            list(generated),
            seed=seed,
            subject_identity=identity,
            catalogs=catalogs,
            tile_x=tile_x,
            tile_y=tile_y,
            lod=GENERATED_LOD,
            grammar_version=version,
        )
        validate_city_document(document, catalogs=catalogs)
        documents.append(document)
    check_city_reference_closure(documents)
    return tuple(documents)


def tile_documents(
    receipt: Mapping[str, Any], generated: Sequence[object]
) -> tuple[TileDocument, ...]:
    """Every tile document the world covers, each checked by the grammar and closed together."""
    version = _version(receipt)
    catalogs = load_city_catalogs(grammar_version=version)
    _check_current(receipt, catalogs)
    return _documents(
        receipt["seed"], receipt["subject_identity"], generated, receipt["tiles"], catalogs, version
    )


def tile_document_bytes(document: TileDocument) -> bytes:
    """A tile document's canonical bytes, the tessellator's input."""
    return document_bytes(document)


def stated_extent(topology: Mapping[str, Any], placement: Mapping[str, Any]) -> StatedExtent:
    """The region, the rectangle the world's tiles cover and its spawn, read from its snapshot.

    Every element is a tile of :data:`REGION_ID` naming one receipt, placed at its tile's
    south-west corner and a whole tile wide; the spawn is the region's one destination. A snapshot
    that states anything else is refused by name rather than read as a town.
    """
    receipt_digest_of(topology)
    regions = tuple(str(region["region_id"]) for region in topology.get("regions", ()))
    if regions != (REGION_ID,):
        raise InvalidStructuralData(f"a generated town states the one region {REGION_ID}")
    placed = {element["element_id"]: element for element in placement.get("elements", ())}
    corners = []
    for element in topology["elements"]:
        where = placed.get(element["element_id"])
        if (
            where is None
            or element["owner"] != {"kind": "region", "id": REGION_ID}
            or (where["y_mm"], where["yaw_microradians"], where["scale_milli"]) != (0, 0, 1_000)
        ):
            raise InvalidStructuralData(
                f"generated tile {element['element_id']} is not placed as a tile of its region"
            )
        corners.append((where["x_mm"], where["z_mm"]))
    destinations = placement.get("destinations", ())
    if [d.get("destination_id") for d in destinations] != [DESTINATION_ID]:
        raise InvalidStructuralData(f"a generated town states its spawn as {DESTINATION_ID}")
    spawn = destinations[0]
    return StatedExtent(
        region_id=REGION_ID,
        region_ids=regions,
        east_mm=(min(x for x, _ in corners), max(x for x, _ in corners) + TILE_SIZE_MM),
        south_mm=(min(z for _, z in corners) - TILE_SIZE_MM, max(z for _, z in corners)),
        arrival_mm=(spawn["x_mm"], spawn["y_mm"], spawn["z_mm"]),
    )


def tile_inputs(receipt: Mapping[str, Any]) -> tuple[tuple[tuple[int, int], str], ...]:
    """Each tile the world covers, with the digest over its bake's inputs: the city seed, the
    grammar pins, the catalog digest and the tile's coordinate and level of detail."""
    version = _version(receipt)
    catalogs = load_city_catalogs(grammar_version=version)
    _check_current(receipt, catalogs)
    return tuple(
        (
            (tile_x, tile_y),
            tile_inputs_digest(
                tile_record(
                    seed=receipt["seed"],
                    catalogs=catalogs,
                    tile_x=tile_x,
                    tile_y=tile_y,
                    lod=GENERATED_LOD,
                    grammar_version=version,
                )
            ),
        )
        for tile_x, tile_y in receipt["tiles"]
    )
