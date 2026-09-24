"""The objects a person may place in a world, as one versioned catalog.

``assets/catalogs/world-objects/world-object.v<N>.json`` states each kind once: the registry key
and the words a person reads (a title and a summary), the recipe its mesh is generated from, the
extent that recipe fills, the texture sets that dress it, and what inhabitants do with it.
Everything else derives from here. :mod:`exulanica.world.assets` generates each kind's mesh from
its recipe and dresses it from the texture library; migrations 0042 and 0105 pin the digests of
those meshes as reviewed asset rows; and :mod:`exulanica.world.society_composition` reads each
kind's use as the society's reviewed affordance, so a new kind is an entry here and a migration
row, never a second table.

**The file sits in a subdirectory** because the city grammar's directory loader refuses any file
in ``assets/catalogs`` it has no schema for, the reason :mod:`exulanica.world.society_catalogs`
gives for ``assets/catalogs/society``. The envelope, the key rule and the licence on every entry
are the grammar's (:func:`exulanica.grammar.catalogs.load_catalog`). A nested value, such as a
recipe or a use, is checked by its own reader below and carried as its canonical JSON text, the one
catalog field value a nested structure fits, so the catalog digest covers it exactly.

**Two recipe profiles.** ``marker-v1`` is the three grey markers the first object milestone
reviewed: a box or a flat plate generated exactly as migration 0042 pinned them, so every world
that holds one keeps its bytes. ``parts-v1`` is a list of the city grammar's form parts
(:class:`exulanica.grammar.grammars.city.common.FormPart`): boxes, prisms and ellipsoids in the
object's own frame, where ``+x`` runs across the object, ``+y`` is its front, the side that faces
the person who places it, and ``+z`` is up, and each offset places a part's bottom centre. A
profile this module does not know is refused by name.

**Every number cites its source.** A part names ``street-furniture.v2/<entry>/<index>``, and the
loader holds it equal to that part of the street furniture catalog, read from that catalog; or it
names ``declared/<key>``, and the entry's ``declared`` map states the measurement and why it was
chosen. A declaration nothing cites is refused, and so is a citation of nothing.

**What inhabitants do with a kind** is its ``use``: an activity the society already has (``rest``
or ``visit``, :data:`exulanica.world.society_planner.DURATIONS`) or ``none``; whether it blocks
walking; and where people stand to use it. Two things are derived rather than stated, so neither
restates a figure kept elsewhere. The footprint a kind blocks is the least rectangle about its
origin that holds every part lower than the city grammar's walker capsule, since a walker passes
under a crown, an awning or a lamp's arm and not under a table top. The places are stated as rows,
a side of the kind and how many people stand along it, and each place is derived from the
society's own figures: the navigation clearance and a standing radius out from that side, and a
standing spacing and :data:`exulanica.world.society_composition.TURNED_PLACE_MARGIN_MM` from its
neighbour, centred on the side. The margin is what turning an object can take from the gap between
two places, so at the kind's own size or larger, turned any way, the society keeps every place. The
markers state no rows, and the society keeps the rules it has always applied to them (one place in
front of each face of a blocking marker, a row along a plate); every other kind with an activity
states its rows, and a kind with no activity states none.

Pure: no connection, no store and no network. The catalog is read once per process.
"""

from __future__ import annotations

import functools
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal

from exulanica.canonical import canonical_json
from exulanica.grammar.catalogs import (
    Catalog,
    CatalogSchema,
    Licence,
    catalog_digest,
    load_catalog,
    text_field,
)
from exulanica.grammar.errors import CatalogError, GrammarError
from exulanica.grammar.grammars.city.common import (
    FORM_PART_SHAPE,
    PART_ROLES,
    ROLE_CLASSES,
    FormPart,
)
from exulanica.grammar.shapes import validate_record
from exulanica.grammar.textures import TextureSet, read_texture_manifest
from exulanica.world.object_meshes import PlanExtent, parts_extent

__all__ = [
    "CATALOG_DIRECTORY",
    "CATALOG_ID",
    "CATALOG_VERSION",
    "MARKER_PROFILE",
    "NO_ACTIVITY",
    "PARTS_PROFILE",
    "SIDES",
    "CatalogPart",
    "MarkerRecipe",
    "ObjectUse",
    "PartsRecipe",
    "PlaceRow",
    "WorldObjectCatalog",
    "WorldObjectKind",
    "load_world_object_catalog",
    "world_object_catalog",
]

CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "world-objects")
)
CATALOG_ID: Final = "world-object"
#: The version a running host reads. A new version is published beside this one and never edits
#: it, because the reviewed rows a migration pinned name the meshes this version's recipes make.
CATALOG_VERSION: Final = 1
MARKER_PROFILE: Final = "marker-v1"
PARTS_PROFILE: Final = "parts-v1"
#: The use of a kind inhabitants do nothing with: it is an obstacle, or nothing at all.
NO_ACTIVITY: Final = "none"
#: The street furniture catalog a part may cite, and where it lives. Only this version is read:
#: a part that cites another is refused rather than compared with a catalog nobody loaded.
_STREET_FURNITURE: Final = ("street-furniture", 2)
_STREET_FURNITURE_FILE: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "street-furniture.v2.json")
)
_ASSET_KEY: Final = re.compile(r"[a-z][a-z0-9.-]*")
_DECLARED_KEY: Final = re.compile(r"[a-z][a-z0-9_]*")
_CITATION: Final = re.compile(
    r"(?:street-furniture\.v2/(?P<entry>[a-z][a-z0-9_]*)/(?P<index>0|[1-9][0-9]*))"
    r"|(?:declared/(?P<declared>[a-z][a-z0-9_]*))"
)
_FORM_PART_FIELDS: Final = tuple(field.name for field in fields(FormPart))
_MARKER_SOLIDS: Final = ("box", "plate")
#: The largest side a published texture set has (assets/textures/manifest.json), the bound on
#: what a recipe may ask its maps to be embedded at.
_MAX_TEXELS: Final = 1024
#: A guard on the sizes the file states, in millimetres: a hundred metres, past any object a
#: person places, so a stray digit is refused where it is read.
_MAX_SIZE_MM: Final = 100_000
_DIMENSIONS: Final = ("width", "depth", "height")
#: The sides a row of places stands along, in the part frame: ``+y`` is the front, the side that
#: faces the person who places the kind, and ``+x`` runs across it.
SIDES: Final = ("+y", "+x", "-y", "-x")

Place = tuple[int, int]


@dataclass(frozen=True, slots=True)
class CatalogPart:
    """One form part and the source its numbers come from."""

    form: FormPart
    source: str


@dataclass(frozen=True, slots=True)
class MarkerRecipe:
    """A grey marker as migration 0042 pinned it: a box, or a plate with no height."""

    solid: Literal["box", "plate"]
    size_x_mm: int
    size_y_mm: int
    size_z_mm: int
    source: str
    profile: str = MARKER_PROFILE


@dataclass(frozen=True, slots=True)
class PartsRecipe:
    """Form parts in the object's own frame, drawn with the texture sets their roles name."""

    parts: tuple[CatalogPart, ...]
    #: The side, in texels, each texture set's maps are embedded at: the set's own side, or that
    #: side over a power of two (:func:`exulanica.world.object_glb.embedded_texture_set`).
    texels: int
    #: Where ``texels`` comes from: a ``declared/<key>`` the entry states.
    texels_source: str
    profile: str = PARTS_PROFILE


Recipe = MarkerRecipe | PartsRecipe


@dataclass(frozen=True, slots=True)
class PlaceRow:
    """People standing side by side along one side of a kind, facing it: ``count`` of them."""

    side: str
    count: int


@dataclass(frozen=True, slots=True)
class ObjectUse:
    """What inhabitants do with a kind, and where it stands in their way.

    ``rows`` is what the entry states: ``None`` for a marker, whose places the society derives
    from its footprint as it always has, and ``()`` for a kind nobody uses. ``places`` is derived
    from them, one person to a place, ``[x, y]`` in the part frame in the rows' order.
    ``footprint_half_extents_mm`` is derived from the recipe, in the object's own ``x`` and depth.
    """

    affordance: str
    blocks_navigation: bool
    footprint_half_extents_mm: tuple[int, int]
    rows: tuple[PlaceRow, ...] | None
    places: tuple[Place, ...] | None

    @property
    def capacity(self) -> int | None:
        """How many people can use the kind at once, or ``None`` where the society derives it."""
        return None if self.places is None else len(self.places)


@dataclass(frozen=True, slots=True)
class WorldObjectKind:
    """One placeable kind, as the catalog states it."""

    key: str
    asset_key: str
    title: str
    summary: str
    recipe: Recipe
    #: Width (``x``), depth (``y``) and height (``z``) of what the recipe draws, in millimetres.
    dimensions_mm: tuple[int, int, int]
    #: Surface role to texture set id. Empty for a marker, which the renderer draws matte.
    materials: Mapping[str, str]
    use: ObjectUse
    declared: Mapping[str, str]
    reason: str
    licence: Licence


@dataclass(frozen=True, slots=True)
class WorldObjectCatalog:
    """One version of the catalog, every kind checked, in file order, with its digest."""

    version: int
    kinds: tuple[WorldObjectKind, ...]
    #: :func:`exulanica.grammar.catalogs.catalog_digest` over the loaded catalog.
    sha256: str

    def by_asset_key(self) -> Mapping[str, WorldObjectKind]:
        return MappingProxyType({kind.asset_key: kind for kind in self.kinds})

    def by_key(self) -> Mapping[str, WorldObjectKind]:
        return MappingProxyType({kind.key: kind for kind in self.kinds})


# -- nested readers -----------------------------------------------------------------------------


def _int(where: str, value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CatalogError(f"{where} is an int in [{minimum}, {maximum}], got {value!r}")
    return value


def _object(where: str, value: object, keys: Sequence[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise CatalogError(f"{where} is an object with exactly {sorted(keys)}")
    return value


def _citation(where: str, value: object) -> str:
    if type(value) is not str or _CITATION.fullmatch(value) is None:
        raise CatalogError(
            f"{where} cites street-furniture.v2/<entry>/<index> or declared/<key>, got {value!r}"
        )
    return value


def _nested(reader: Callable[[str, object], object]) -> Callable[[str, object], str]:
    """A catalog field check that reads a nested value and carries it as canonical JSON text."""

    def check(where: str, value: object) -> str:
        reader(where, value)
        return canonical_json(value).decode("utf-8")

    return check


def _read_part(where: str, value: object) -> CatalogPart:
    item = _object(where, value, (*_FORM_PART_FIELDS, "source"))
    try:
        form = FormPart(**{name: item[name] for name in _FORM_PART_FIELDS})
        validate_record(form, FORM_PART_SHAPE)
    except (GrammarError, TypeError) as error:
        raise CatalogError(f"{where}: {error}") from error
    return CatalogPart(form, _citation(f"{where}.source", item["source"]))


def _read_recipe(where: str, value: object) -> Recipe:
    if not isinstance(value, dict) or "profile" not in value:
        raise CatalogError(f"{where} is an object naming its profile")
    profile = value["profile"]
    if profile == MARKER_PROFILE:
        item = _object(
            where, value, ("profile", "solid", "size_x_mm", "size_y_mm", "size_z_mm", "source")
        )
        solid = item["solid"]
        if solid not in _MARKER_SOLIDS:
            raise CatalogError(f"{where}.solid is one of {_MARKER_SOLIDS}, got {solid!r}")
        size_x = _int(f"{where}.size_x_mm", item["size_x_mm"], 1, _MAX_SIZE_MM)
        size_y = _int(f"{where}.size_y_mm", item["size_y_mm"], 1, _MAX_SIZE_MM)
        # A plate has no height, and a box has one: the flat marker is the only solid of no depth.
        low = 0 if solid == "plate" else 1
        high = 0 if solid == "plate" else _MAX_SIZE_MM
        size_z = _int(f"{where}.size_z_mm", item["size_z_mm"], low, high)
        return MarkerRecipe(
            solid, size_x, size_y, size_z, _citation(f"{where}.source", item["source"])
        )
    if profile == PARTS_PROFILE:
        item = _object(where, value, ("profile", "texels", "texels_source", "parts"))
        parts = item["parts"]
        if not isinstance(parts, list) or not parts:
            raise CatalogError(f"{where}.parts is a non-empty list of parts")
        return PartsRecipe(
            tuple(_read_part(f"{where}.parts[{index}]", part) for index, part in enumerate(parts)),
            _int(f"{where}.texels", item["texels"], 1, _MAX_TEXELS),
            _citation(f"{where}.texels_source", item["texels_source"]),
        )
    raise CatalogError(
        f"{where}.profile is {MARKER_PROFILE!r} or {PARTS_PROFILE!r}, got {profile!r}; a recipe "
        "profile nothing generates is refused, never drawn as something else"
    )


def _read_dimensions(where: str, value: object) -> tuple[int, int, int]:
    item = _object(where, value, _DIMENSIONS)
    width, depth, height = (
        _int(f"{where}.{name}", item[name], 0, _MAX_SIZE_MM) for name in _DIMENSIONS
    )
    return (width, depth, height)


def _read_materials(where: str, value: object) -> Mapping[str, str]:
    if not isinstance(value, dict):
        raise CatalogError(f"{where} maps surface roles to texture set ids")
    for role, set_id in value.items():
        if role not in PART_ROLES:
            raise CatalogError(f"{where}: {role!r} is not a part role, one of {PART_ROLES}")
        if type(set_id) is not str or not set_id:
            raise CatalogError(f"{where}.{role} names a texture set id")
    return MappingProxyType(dict(value))


def _read_row(where: str, value: object) -> PlaceRow:
    item = _object(where, value, ("side", "count"))
    side = item["side"]
    if side not in SIDES:
        raise CatalogError(f"{where}.side is one of {SIDES}, got {side!r}")
    return PlaceRow(side, _int(f"{where}.count", item["count"], 1, _MAX_SIZE_MM))


@dataclass(frozen=True, slots=True)
class _StatedUse:
    """A use as the entry states it, before its footprint and places are derived."""

    affordance: str
    blocks_navigation: bool
    rows: tuple[PlaceRow, ...] | None


def _read_use(where: str, value: object) -> _StatedUse:
    item = _object(where, value, ("affordance", "blocks_navigation", "places"))
    affordance = item["affordance"]
    if affordance not in _affordances():
        raise CatalogError(f"{where}.affordance is one of {_affordances()}, got {affordance!r}")
    blocks = item["blocks_navigation"]
    if type(blocks) is not bool:
        raise CatalogError(f"{where}.blocks_navigation is true or false")
    rows = item["places"]
    if rows is None:
        return _StatedUse(affordance, blocks, None)
    if not isinstance(rows, list):
        raise CatalogError(
            f"{where}.places is a list of rows, each a side and a count, or null for a marker"
        )
    return _StatedUse(
        affordance,
        blocks,
        tuple(_read_row(f"{where}.places[{index}]", row) for index, row in enumerate(rows)),
    )


def _read_declared(where: str, value: object) -> Mapping[str, str]:
    if not isinstance(value, dict):
        raise CatalogError(f"{where} maps a declared key to the sentence that states it")
    for key, sentence in value.items():
        if _DECLARED_KEY.fullmatch(key) is None:
            raise CatalogError(f"{where}: {key!r} is not a lowercase key")
        text_field(f"{where}.{key}", sentence)
    return MappingProxyType(dict(value))


def _asset_key(where: str, value: object) -> str:
    if type(value) is not str or _ASSET_KEY.fullmatch(value) is None or len(value) > 200:
        raise CatalogError(f"{where} is a registry key matching [a-z][a-z0-9.-]*, got {value!r}")
    return value


def _affordances() -> tuple[str, ...]:
    """The activities the society has, and the use of a kind nobody uses, in that order."""
    from exulanica.world.society_planner import DURATIONS

    return (*sorted(DURATIONS), NO_ACTIVITY)


_SCHEMAS: Final[Mapping[int, CatalogSchema]] = MappingProxyType(
    {
        1: CatalogSchema(
            CATALOG_ID,
            1,
            (
                ("asset_key", _asset_key),
                ("title", text_field),
                ("summary", text_field),
                ("recipe", _nested(_read_recipe)),
                ("dimensions_mm", _nested(_read_dimensions)),
                ("materials", _nested(_read_materials)),
                ("use", _nested(_read_use)),
                ("declared", _nested(_read_declared)),
                ("reason", text_field),
            ),
        )
    }
)


# -- the checks across one kind and across catalogs ---------------------------------------------


def _street_furniture_parts() -> Mapping[str, tuple[FormPart, ...]]:
    """Every street furniture entry's parts, read with the city grammar's own schema."""
    from exulanica.grammar.grammars.city.catalogs import (
        city_catalog_schemas,
        entry_fields,
        form_parts,
    )

    schema = next(
        candidate
        for candidate in city_catalog_schemas(texture_sets=read_texture_manifest())
        if (candidate.catalog_id, candidate.catalog_version) == _STREET_FURNITURE
    )
    catalog = load_catalog(_STREET_FURNITURE_FILE, schema)
    return MappingProxyType(
        {
            entry.key: form_parts(entry_fields(catalog, entry.key)["parts"])
            for entry in catalog.entries
        }
    )


def _square_sides() -> Mapping[str, int]:
    """Each published square set's side in texels, read from the manifest's one reader."""
    from exulanica.grammar.textures import MANIFEST_PATH
    from exulanica.materials.manifest import read_texture_manifest as read_entries

    entries = read_entries(MANIFEST_PATH.read_bytes(), MANIFEST_PATH.name)
    return MappingProxyType(
        {set_id: entry.width for set_id, entry in entries.items() if entry.width == entry.height}
    )


def _check_citations(kind: WorldObjectKind, furniture: Mapping[str, tuple[FormPart, ...]]) -> None:
    where = f"world object {kind.key}"
    cited: set[str] = set()
    recipe = kind.recipe
    sources = (
        [(recipe.source, None)]
        if isinstance(recipe, MarkerRecipe)
        else [(recipe.texels_source, None), *((part.source, part.form) for part in recipe.parts)]
    )
    for source, form in sources:
        match = _CITATION.fullmatch(source)
        assert match is not None
        if match["declared"] is not None:
            if match["declared"] not in kind.declared:
                raise CatalogError(f"{where} cites {source}, which it does not declare")
            cited.add(match["declared"])
            continue
        entry, index = match["entry"], int(match["index"])
        stated = furniture.get(entry)
        if stated is None or index >= len(stated):
            raise CatalogError(f"{where} cites {source}, which the street furniture catalog lacks")
        if form != stated[index]:
            raise CatalogError(
                f"{where} cites {source} and differs from it: a cited part is that part exactly"
            )
    unused = sorted(set(kind.declared) - cited)
    if unused:
        raise CatalogError(f"{where} declares {unused} and no number cites them")


def _check_materials(
    kind: WorldObjectKind,
    texture_sets: Mapping[str, TextureSet],
    resolutions: Mapping[str, int],
) -> None:
    where = f"world object {kind.key}"
    if isinstance(kind.recipe, MarkerRecipe):
        if kind.materials:
            raise CatalogError(f"{where} is a marker, drawn matte by the renderer, so it has none")
        return
    roles = {part.form.surface_role for part in kind.recipe.parts}
    if roles != set(kind.materials):
        raise CatalogError(
            f"{where}: its parts take the roles {sorted(roles)} and it dresses "
            f"{sorted(kind.materials)}; every role a part takes is dressed, and only those"
        )
    for role, set_id in sorted(kind.materials.items()):
        texture = texture_sets.get(set_id)
        if texture is None:
            raise CatalogError(f"{where} dresses {role} with {set_id}, which is not published")
        admitted = ROLE_CLASSES[role]
        if texture.material_class not in admitted:
            raise CatalogError(
                f"{where} dresses {role} with {set_id}, a {texture.material_class} set; "
                f"{role} admits {admitted}"
            )
        side = resolutions.get(set_id)
        texels = kind.recipe.texels
        factor, remainder = divmod(side, texels) if side is not None else (0, 1)
        if side is None or remainder or factor & (factor - 1):
            raise CatalogError(
                f"{where} embeds {set_id} at {texels} texels a side, which is not the set's own "
                "square side over a power of two"
            )


def _extent_of(recipe: Recipe) -> PlanExtent:
    if isinstance(recipe, MarkerRecipe):
        half_x, half_y = recipe.size_x_mm / 2, recipe.size_y_mm / 2
        return PlanExtent(
            math.floor(-half_x),
            math.floor(-half_y),
            0,
            math.ceil(half_x),
            math.ceil(half_y),
            recipe.size_z_mm,
        )
    return parts_extent(tuple(part.form for part in recipe.parts))


@functools.cache
def _capsule_height_mm() -> int:
    """The walker capsule's height, read where the city grammar reads it for its nav envelope."""
    from exulanica.grammar.grammars.city import CITY_GRAMMAR

    return next(
        dict(row.measures)["height_mm"]
        for row in CITY_GRAMMAR.projection("nav_envelope").preserved
        if row.property == "capsule_clearance"
    )


def _footprint_of(where: str, recipe: Recipe) -> tuple[int, int]:
    """The least rectangle about the origin holding every part lower than a walker's capsule.

    A part whose bottom is below the capsule's height stands where a walker would be; a crown, an
    awning or a lamp's arm wholly above it does not. A marker is one such part.
    """
    if isinstance(recipe, MarkerRecipe):
        extent = _extent_of(recipe)
    else:
        low = tuple(
            part.form for part in recipe.parts if part.form.offset_z_mm < _capsule_height_mm()
        )
        if not low:
            raise CatalogError(
                f"{where} has no part lower than the {_capsule_height_mm()} mm walker capsule, so "
                "nothing of it stands where a person walks"
            )
        extent = parts_extent(low)
    return (max(-extent.min_x, extent.max_x), max(-extent.min_y, extent.max_y))


def _half_away(twice: int) -> int:
    """Half of ``twice``, a half moved away from zero, so centred places keep their gaps."""
    return twice // 2 if twice >= 0 else -(-twice // 2)


def _row_places(row: PlaceRow, footprint: tuple[int, int], out: int, step: int) -> list[Place]:
    """One row's places: ``out`` from its side of the footprint, ``step`` apart, centred on it."""
    hx, hy = footprint
    along = [_half_away((2 * index - row.count + 1) * step) for index in range(row.count)]
    if row.side == "+y":
        return [(a, hy + out) for a in along]
    if row.side == "-y":
        return [(a, -(hy + out)) for a in along]
    if row.side == "+x":
        return [(hx + out, a) for a in along]
    return [(-(hx + out), a) for a in along]


def _place_figures() -> tuple[int, int]:
    """How far out from a side a place stands, and how far apart two places in a row stand.

    Read where the society reads them: the navigation clearance and a standing radius, so the
    whole body stands outside the line no walker's centre crosses, and a standing spacing and the
    margin turning an object can take from the gap between two places.
    """
    from exulanica.world.society_catalogs import load_routine_model
    from exulanica.world.society_composition import TURNED_PLACE_MARGIN_MM
    from exulanica.world.society_planner import CLEARANCE_MM

    policy = load_routine_model().policy
    return (
        CLEARANCE_MM + policy["standing_radius_mm"],
        policy["standing_spacing_mm"] + TURNED_PLACE_MARGIN_MM,
    )


def _derived_use(where: str, recipe: Recipe, stated: _StatedUse) -> ObjectUse:
    footprint = _footprint_of(where, recipe)
    if stated.rows is None:
        return ObjectUse(stated.affordance, stated.blocks_navigation, footprint, None, None)
    out, step = _place_figures()
    places = tuple(place for row in stated.rows for place in _row_places(row, footprint, out, step))
    return ObjectUse(stated.affordance, stated.blocks_navigation, footprint, stated.rows, places)


def _check_use(kind: WorldObjectKind) -> None:
    from exulanica.world.society_composition import MAX_REACH_MM

    where = f"world object {kind.key}"
    use = kind.use
    marker = isinstance(kind.recipe, MarkerRecipe)
    if marker != (use.rows is None):
        raise CatalogError(
            f"{where}: a marker states no places, since the society keeps its rules for them, and "
            "every other kind states its places"
        )
    if use.rows is None or use.places is None:
        return
    if (use.affordance == NO_ACTIVITY) != (not use.rows):
        raise CatalogError(f"{where}: a kind nobody uses has no places, and a used kind has some")
    if use.rows and not use.blocks_navigation:
        raise CatalogError(
            f"{where}: places stand out from what a kind blocks, and this kind blocks nothing"
        )
    _, step = _place_figures()
    hx, hy = use.footprint_half_extents_mm
    for row in use.rows:
        side = hx if row.side in ("+y", "-y") else hy
        if (row.count - 1) * step > 2 * side:
            raise CatalogError(
                f"{where}: {row.count} places {step} mm apart do not fit along its {row.side} "
                f"side, {2 * side} mm long"
            )
    for index, place in enumerate(use.places):
        if max(abs(place[0]), abs(place[1])) > MAX_REACH_MM:
            raise CatalogError(
                f"{where} place {index} {list(place)} stands farther than {MAX_REACH_MM} mm from "
                "its centre, the farthest a registry row allows"
            )
        for other in use.places[:index]:
            if (place[0] - other[0]) ** 2 + (place[1] - other[1]) ** 2 < step**2:
                raise CatalogError(
                    f"{where} places {list(other)} and {list(place)} stand closer than a standing "
                    f"spacing and the turning margin, {step} mm"
                )


def _check_kind(
    kind: WorldObjectKind,
    *,
    texture_sets: Mapping[str, TextureSet],
    resolutions: Mapping[str, int],
    furniture: Mapping[str, tuple[FormPart, ...]],
) -> None:
    _check_citations(kind, furniture)
    _check_materials(kind, texture_sets, resolutions)
    extent = _extent_of(kind.recipe)
    drawn = (
        extent.max_x - extent.min_x,
        extent.max_y - extent.min_y,
        extent.max_z - extent.min_z,
    )
    if drawn != kind.dimensions_mm:
        raise CatalogError(
            f"world object {kind.key} states dimensions {list(kind.dimensions_mm)} and its recipe "
            f"draws {list(drawn)}"
        )
    _check_use(kind)


def _kind(catalog: Catalog, index: int) -> WorldObjectKind:
    entry = catalog.entries[index]
    values = dict(entry.values)
    where = f"{CATALOG_ID} {entry.key}"

    def nested(name: str) -> object:
        return json.loads(str(values[name]))

    recipe = _read_recipe(f"{where}.recipe", nested("recipe"))
    return WorldObjectKind(
        key=entry.key,
        asset_key=str(values["asset_key"]),
        title=str(values["title"]),
        summary=str(values["summary"]),
        recipe=recipe,
        dimensions_mm=_read_dimensions(f"{where}.dimensions_mm", nested("dimensions_mm")),
        materials=_read_materials(f"{where}.materials", nested("materials")),
        use=_derived_use(where, recipe, _read_use(f"{where}.use", nested("use"))),
        declared=_read_declared(f"{where}.declared", nested("declared")),
        reason=str(values["reason"]),
        licence=entry.licence,
    )


def load_world_object_catalog(
    directory: Path = CATALOG_DIRECTORY,
    version: int = CATALOG_VERSION,
    *,
    texture_sets: Mapping[str, TextureSet] | None = None,
) -> WorldObjectCatalog:
    """Read one version of the catalog and check every kind, or refuse with a ``CatalogError``.

    ``texture_sets`` defaults to the published texture manifest, read strictly. The directory is
    asked what it holds: a file no schema claims, or a schema with no file, is refused, so a
    version a reviewed row was generated from cannot quietly leave it.
    """
    claimed = {f"{CATALOG_ID}.v{number}.json" for number in _SCHEMAS}
    present = {path.name for path in directory.glob("*.json") if path.name.startswith(CATALOG_ID)}
    if present != claimed:
        raise CatalogError(
            f"{directory}: files with no schema {sorted(present - claimed)}, "
            f"schemas with no file {sorted(claimed - present)}"
        )
    schema = _SCHEMAS.get(version)
    if schema is None:
        raise CatalogError(f"{CATALOG_ID} v{version} has no schema")
    catalog = load_catalog(directory.joinpath(f"{CATALOG_ID}.v{version}.json"), schema)
    kinds = tuple(_kind(catalog, index) for index in range(len(catalog.entries)))
    asset_keys = [kind.asset_key for kind in kinds]
    if len(set(asset_keys)) != len(asset_keys):
        raise CatalogError(f"{CATALOG_ID} v{version} names one registry key for two kinds")
    published = read_texture_manifest() if texture_sets is None else texture_sets
    resolutions = _square_sides()
    furniture = _street_furniture_parts()
    for kind in kinds:
        _check_kind(kind, texture_sets=published, resolutions=resolutions, furniture=furniture)
    return WorldObjectCatalog(version, kinds, catalog_digest([catalog]))


@functools.cache
def world_object_catalog() -> WorldObjectCatalog:
    """The catalog a running host reads, loaded and checked once per process."""
    return load_world_object_catalog()
