"""The kinds that fly, as one versioned catalog, and the reviewed assets their bodies are drawn in.

``assets/catalogs/movement/flight-kind.v<N>.json`` states each flying kind once: the movement
module it flies by, the words a person reads, a value for every parameter that module lets a kind
supply, each citing the ``declared`` sentence that says why, and the recipes its body and one wing
are generated from, in the world object catalog's ``parts-v1`` form. Everything else derives from
here: the flight module checks every value against its own bounds
(:meth:`exulanica.movement.flight.FlightKind.checked`), and :func:`flight_assets` generates the
body and the wing as reviewed assets, which migration 0114 pins as components, so the renderer
fetches them by key like a character's parts.

**Which objects a kind lives on** is not stated here but on each object kind, as its ``hosts``
(:mod:`exulanica.world.object_catalog`, version 3). This module holds the two catalogs to each
other: every hosted kind exists here, and every host declares at least as many perches wide
enough for the kind as it hosts flyers of it.

**A kind names its module, and an unknown module is refused by name** through the movement
dispatcher (:func:`exulanica.movement.registry.built_module`); a module whose agents come from
another catalog is refused too.

The geometry is authored for this repository and generated rather than committed, as the world
objects are (:mod:`exulanica.world.assets`), and dedicated to the public domain under CC0 1.0 with
the texture maps it embeds.

Pure: no connection and no store. The catalog is read once per process.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.catalogs import (
    Catalog,
    CatalogSchema,
    Licence,
    catalog_digest,
    load_catalog,
    text_field,
)
from exulanica.grammar.errors import CatalogError
from exulanica.movement.flight import FlightKind, FlightRefused
from exulanica.movement.registry import MovementError, movement_module
from exulanica.world.asset_kinds import AssetKind
from exulanica.world.assets import CC0_TEXTURED_LICENCE_TEXT, ReviewedAsset
from exulanica.world.object_catalog import (
    PartsRecipe,
    WorldObjectCatalog,
    check_dressing,
    read_declared,
    read_parts_recipe,
    world_object_catalog,
)
from exulanica.world.object_glb import embedded_texture_set, textured_glb
from exulanica.world.object_meshes import form_triangles, parts_extent

__all__ = [
    "CATALOG_DIRECTORY",
    "CATALOG_ID",
    "CATALOG_VERSION",
    "FlightKindCatalog",
    "FlyingKind",
    "flight_assets",
    "flight_kind_catalog",
    "load_flight_kind_catalog",
]

CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "movement")
)
CATALOG_ID: Final = "flight-kind"
#: The version a running host reads. A new version is published beside it and never edits it,
#: because the reviewed rows migration 0114 pinned name the bodies this version's recipes make.
CATALOG_VERSION: Final = 1
_DECLARED: Final = re.compile(r"declared/(?P<key>[a-z][a-z0-9_]*)")
_MAX_OFFSET_MM: Final = 100_000


@dataclass(frozen=True, slots=True)
class FlyingKind:
    """One flying kind, as the catalog states it."""

    key: str
    module: str
    title: str
    summary: str
    figures: FlightKind
    #: Each parameter's ``declared/<key>``.
    sources: Mapping[str, str]
    body: PartsRecipe
    wing: PartsRecipe
    #: Where the right wing's root joins the body, in the body's part frame; the left is mirrored.
    wing_hinge_mm: tuple[int, int, int]
    materials: Mapping[str, str]
    declared: Mapping[str, str]
    reason: str
    licence: Licence

    @property
    def body_asset_key(self) -> str:
        return f"cc0.{self.key.replace('_', '-')}-body"

    @property
    def wing_asset_key(self) -> str:
        return f"cc0.{self.key.replace('_', '-')}-wing"


@dataclass(frozen=True, slots=True)
class FlightKindCatalog:
    """One version of the catalog, every kind checked, in file order, with its digest."""

    version: int
    kinds: tuple[FlyingKind, ...]
    sha256: str

    def by_key(self) -> Mapping[str, FlyingKind]:
        return MappingProxyType({kind.key: kind for kind in self.kinds})


def _object(where: str, value: object, keys: tuple[str, ...]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise CatalogError(f"{where} is an object with exactly {sorted(keys)}")
    return value


def _declared_source(where: str, value: object) -> str:
    if type(value) is not str or _DECLARED.fullmatch(value) is None:
        raise CatalogError(f"{where} cites declared/<key>, got {value!r}")
    return value


def _read_module(where: str, value: object) -> str:
    """A module the registry states whose agents are flying kinds. Whether it is built is asked
    where a flight is made or served, so a kind stays readable while its module is switched off."""
    try:
        module = movement_module(value)
    except MovementError as error:
        raise CatalogError(f"{where}: {error}") from error
    if module.agents_catalog != CATALOG_ID:
        raise CatalogError(
            f"{where}: {module.module} moves agents of {module.agents_catalog}, not {CATALOG_ID}"
        )
    return module.module


def _read_parameters(where: str, value: object) -> Mapping[str, Mapping[str, object]]:
    if not isinstance(value, dict):
        raise CatalogError(f"{where} maps each parameter to its value and source")
    for name, item in value.items():
        row = _object(f"{where}.{name}", item, ("source", "value"))
        _declared_source(f"{where}.{name}.source", row["source"])
    return value


def _read_hinge(where: str, value: object) -> Mapping[str, object]:
    row = _object(where, value, ("x_mm", "y_mm", "z_mm", "source"))
    for axis in ("x_mm", "y_mm", "z_mm"):
        figure = row[axis]
        if type(figure) is not int or not -_MAX_OFFSET_MM <= figure <= _MAX_OFFSET_MM:
            raise CatalogError(f"{where}.{axis} is an int within {_MAX_OFFSET_MM} mm")
    _declared_source(f"{where}.source", row["source"])
    return row


def _read_materials(where: str, value: object) -> Mapping[str, str]:
    if not isinstance(value, dict) or any(
        type(role) is not str or type(set_id) is not str or not set_id
        for role, set_id in value.items()
    ):
        raise CatalogError(f"{where} maps surface roles to texture set ids")
    return MappingProxyType(dict(value))


def _nested(reader: Any) -> Any:
    """A catalog field check that reads a nested value and carries it as canonical JSON text."""

    def check(where: str, value: object) -> str:
        reader(where, value)
        return canonical_json(value).decode("utf-8")

    return check


def _schema(version: int) -> CatalogSchema:
    return CatalogSchema(
        CATALOG_ID,
        version,
        (
            ("module", _read_module),
            ("title", text_field),
            ("summary", text_field),
            ("parameters", _nested(_read_parameters)),
            ("body", _nested(read_parts_recipe)),
            ("wing", _nested(read_parts_recipe)),
            ("wing_hinge_mm", _nested(_read_hinge)),
            ("materials", _nested(_read_materials)),
            ("declared", _nested(read_declared)),
            ("reason", text_field),
        ),
    )


_SCHEMAS: Final[Mapping[int, CatalogSchema]] = MappingProxyType({1: _schema(1)})


def _kind(catalog: Catalog, index: int) -> FlyingKind:
    entry = catalog.entries[index]
    values = dict(entry.values)
    where = f"{CATALOG_ID} {entry.key}"

    def nested(name: str) -> Any:
        return json.loads(str(values[name]))

    parameters = nested("parameters")
    try:
        figures = FlightKind.checked(
            entry.key, {name: row["value"] for name, row in parameters.items()}
        )
    except (FlightRefused, MovementError) as error:
        raise CatalogError(f"{where}: {error}") from error
    hinge = nested("wing_hinge_mm")
    kind = FlyingKind(
        key=entry.key,
        module=str(values["module"]),
        title=str(values["title"]),
        summary=str(values["summary"]),
        figures=figures,
        sources=MappingProxyType({name: row["source"] for name, row in parameters.items()}),
        body=read_parts_recipe(f"{where}.body", nested("body")),
        wing=read_parts_recipe(f"{where}.wing", nested("wing")),
        wing_hinge_mm=(hinge["x_mm"], hinge["y_mm"], hinge["z_mm"]),
        materials=_read_materials(f"{where}.materials", nested("materials")),
        declared=read_declared(f"{where}.declared", nested("declared")),
        reason=str(values["reason"]),
        licence=entry.licence,
    )
    _check_kind(kind, hinge_source=str(hinge["source"]))
    return kind


def _check_kind(kind: FlyingKind, *, hinge_source: str) -> None:
    where = f"flight kind {kind.key}"
    roles = {part.form.surface_role for part in (*kind.body.parts, *kind.wing.parts)}
    if roles != set(kind.materials):
        raise CatalogError(
            f"{where}: its parts take the roles {sorted(roles)} and it dresses "
            f"{sorted(kind.materials)}; every role a part takes is dressed, and only those"
        )
    for label, recipe in (("body", kind.body), ("wing", kind.wing)):
        check_dressing(f"{where} {label}", recipe, _dressing(kind, recipe))
    sources = [
        *kind.sources.values(),
        hinge_source,
        kind.body.texels_source,
        kind.wing.texels_source,
        *(part.source for part in (*kind.body.parts, *kind.wing.parts)),
    ]
    cited = set()
    for source in sources:
        match = _DECLARED.fullmatch(source)
        if match is None:
            raise CatalogError(f"{where} cites {source}; a flight kind cites declared/<key> only")
        if match["key"] not in kind.declared:
            raise CatalogError(f"{where} cites {source}, which it does not declare")
        cited.add(match["key"])
    unused = sorted(set(kind.declared) - cited)
    if unused:
        raise CatalogError(f"{where} declares {unused} and no number cites them")
    wing = parts_extent(tuple(part.form for part in kind.wing.parts))
    drawn = 2 * (kind.wing_hinge_mm[0] + wing.max_x)
    if drawn != kind.figures.body_span_mm:
        raise CatalogError(
            f"{where} states a span of {kind.figures.body_span_mm} mm and its body and wings "
            f"draw {drawn} mm"
        )


def check_hosts(objects: WorldObjectCatalog, flying: FlightKindCatalog) -> None:
    """Every kind an object hosts flies, and the object's perches can start all its flyers.

    An object's perches are one pool: its widest kinds draw first, as the composer draws them,
    since a perch wide enough for a wide kind is wide enough for a narrower one.
    """
    kinds = flying.by_key()
    for kind in objects.kinds:
        for host in kind.hosts:
            if host.kind not in kinds:
                raise CatalogError(
                    f"world object {kind.key} hosts {host.kind}, which the flight kind catalog "
                    "does not state"
                )
        taken: set[int] = set()
        for host in sorted(
            kind.hosts, key=lambda host: (-kinds[host.kind].figures.body_span_mm, host.kind)
        ):
            span = kinds[host.kind].figures.body_span_mm
            wide = [
                index
                for index, perch in enumerate(kind.perches)
                if index not in taken and perch.span_mm >= span
            ]
            if len(wide) < host.count:
                raise CatalogError(
                    f"world object {kind.key} hosts {host.count} {host.kind} and has {len(wide)} "
                    f"perches left at least {span} mm wide to start them on"
                )
            taken.update(wide[: host.count])


def load_flight_kind_catalog(
    directory: Path = CATALOG_DIRECTORY, version: int = CATALOG_VERSION
) -> FlightKindCatalog:
    """Read one version of the catalog and check every kind, or refuse with a ``CatalogError``."""
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
    return FlightKindCatalog(version, kinds, catalog_digest([catalog]))


@functools.cache
def flight_kind_catalog() -> FlightKindCatalog:
    """The catalog a running host reads, checked against the object catalog's hosts, once."""
    catalog = load_flight_kind_catalog()
    check_hosts(world_object_catalog(), catalog)
    return catalog


def _dressing(kind: FlyingKind, recipe: PartsRecipe) -> Mapping[str, str]:
    """The texture sets that dress one of a kind's recipes: its materials for the roles it takes."""
    roles = {part.form.surface_role for part in recipe.parts}
    return {role: set_id for role, set_id in kind.materials.items() if role in roles}


def _asset(
    key: str, title: str, summary: str, name: str, recipe: PartsRecipe, kind: FlyingKind
) -> ReviewedAsset:
    triangles = form_triangles(tuple(part.form for part in recipe.parts))
    materials = {
        role: embedded_texture_set(set_id, recipe.texels)
        for role, set_id in _dressing(kind, recipe).items()
    }
    return ReviewedAsset(
        asset_key=key,
        title=title,
        summary=summary,
        payload=textured_glb(name, triangles, materials),
        kind=AssetKind.COMPONENT,
        licence_text=CC0_TEXTURED_LICENCE_TEXT,
    )


@functools.cache
def flight_assets() -> tuple[ReviewedAsset, ...]:
    """Every flying kind's body and wing, in the catalog's order, as the reviewed components
    migration 0114 pins."""
    assets = []
    for kind in flight_kind_catalog().kinds:
        assets.append(
            _asset(
                kind.body_asset_key,
                f"{kind.title}: body",
                f"The body of a {kind.title.lower()}, drawn by the flight renderer.",
                f"{kind.key}-body",
                kind.body,
                kind,
            )
        )
        assets.append(
            _asset(
                kind.wing_asset_key,
                f"{kind.title}: wing",
                f"One wing of a {kind.title.lower()}, drawn on both sides of its body.",
                f"{kind.key}-wing",
                kind.wing,
                kind,
            )
        )
    return tuple(assets)
