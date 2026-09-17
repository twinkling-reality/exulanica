"""Material classes, and exactly what a texture set container of each class holds.

A set is drawn by its class and by nothing else: never by its id, its title or its family. The
class says how a renderer draws it, and the class with the maker's kind says which maps the
container holds, in which order and packed how. Nothing here is a default. A reader holds a
container to exactly one of the layouts below, and a class or layout it was not written for is a
refusal, never a guess.

``web/packages/loom-texture/src/classes.ts`` states the same tables, and the shared cases in
``web/packages/loom-texture/test/texture-set-cases.json`` hold the two, and the browser's reader, to
the same outcome for every container. The meanings are glTF 2.0's wherever glTF has one:

- ``opaque``: metallic-roughness, ``alphaMode: OPAQUE``. Every set published before this module.
- ``cutout``: ``alphaMode: MASK`` with :data:`ALPHA_CUTOFF`, lit on both faces. Foliage.
- ``decal``: ``alphaMode: BLEND`` on geometry laid over another surface. Road paint.
- ``glazing``: metalness 0 with ``KHR_materials_transmission`` and ``KHR_materials_ior``. The base
  colour tints transmitted light; where transmission is below 255 the rest is a film lit with the
  same colour and roughness.

The list is closed and append-only: a class is never renamed, and a new one is a new entry that
every reader refuses until it is taught it.

A procedural maker computes every texel from a recipe, so its set rebakes exactly and leaves out
what a rebake restores: no height map, and a normal of two components. A model-made set is a
generative model's output; GPU generation is not bit-exact, so its bytes are the artifact and it
ships every map the model produced, the normal as the model produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "ALPHA_CUTOFF",
    "BASE_COLOR",
    "BASE_COLOR_COVERAGE",
    "GLAZING_IOR_MILLIONTHS",
    "HEIGHT",
    "MAKER_KINDS",
    "MATERIAL_CLASSES",
    "NORMAL_CONVENTION",
    "NORMAL_XY",
    "NORMAL_XYZ",
    "ORM",
    "RELIEF_CLASSES",
    "TEXTURE_SET_PROFILES",
    "TEXTURE_SET_PROFILE_V1",
    "TEXTURE_SET_PROFILE_V2",
    "TRANSMISSION_ROUGHNESS",
    "V1_LAYOUT",
    "V2_HEADER_KEYS",
    "GlazingFilm",
    "TextureMap",
    "allowed_channels",
    "class_layout",
    "class_parameters",
    "coverage_permille",
    "declared_film",
    "relief_keys",
]

MATERIAL_CLASSES: Final = ("opaque", "cutout", "decal", "glazing")
MAKER_KINDS: Final = ("procedural", "model")

#: The four-map opaque layout every set published before material classes uses.
TEXTURE_SET_PROFILE_V1: Final = "exulanica.texture-set/v1"
#: A container that states its class, its maker's kind and that class's layout.
TEXTURE_SET_PROFILE_V2: Final = "exulanica.texture-set/v2"
TEXTURE_SET_PROFILES: Final = (TEXTURE_SET_PROFILE_V1, TEXTURE_SET_PROFILE_V2)

#: The classes whose procedural makers bake a height field, and so state its range and cavity.
RELIEF_CLASSES: Final = ("opaque", "cutout", "decal")

NORMAL_CONVENTION: Final = "glTF: +X toward increasing u, +Y toward row 0, +Z out of the surface"

#: glTF's default ``alphaCutoff`` of 0.5, as a byte. A cutout maker designs its coverage around it.
ALPHA_CUTOFF: Final = 128
#: glTF's ``KHR_materials_ior`` default, and the 0.04 reflectance at normal incidence every
#: physically based renderer assumes for glass; soda-lime float glass is about 1.52.
GLAZING_IOR_MILLIONTHS: Final = 1_500_000


@dataclass(frozen=True, slots=True)
class TextureMap:
    """One map in a set, exactly as a header states it, less its offset and length."""

    name: str
    components: int
    holds: tuple[str, ...]
    srgb: bool
    decode: str
    #: Stated by a normal map only.
    space: str | None
    convention: str | None

    def as_channel(self) -> dict[str, Any]:
        """What a manifest entry states of the map: its packing, without the prose."""
        return {
            "map": self.name,
            "components": self.components,
            "holds": list(self.holds),
            "srgb": self.srgb,
        }

    def as_descriptor(self) -> dict[str, Any]:
        """What a container header states of the map, less ``byte_offset`` and ``byte_length``."""
        descriptor: dict[str, Any] = {
            "name": self.name,
            "components": self.components,
            "holds": list(self.holds),
            "srgb": self.srgb,
            "decode": self.decode,
        }
        if self.space is not None:
            descriptor["space"] = self.space
        if self.convention is not None:
            descriptor["convention"] = self.convention
        return descriptor


BASE_COLOR: Final = TextureMap(
    "base_color",
    3,
    ("red", "green", "blue"),
    True,
    "sRGB transfer function to linear reflectance",
    None,
    None,
)
#: Colour and coverage in one map, as ``SRGB8_ALPHA8`` holds them: sRGB colour, linear coverage.
BASE_COLOR_COVERAGE: Final = TextureMap(
    "base_color_coverage",
    4,
    ("red", "green", "blue", "coverage"),
    True,
    "red, green and blue: sRGB transfer function to linear reflectance; coverage: b / 255, "
    "linear, 0 where nothing covers",
    None,
    None,
)
NORMAL_XYZ: Final = TextureMap(
    "normal",
    3,
    ("normal_x", "normal_y", "normal_z"),
    False,
    "n = 2 * b / 255 - 1 per component, then normalise",
    "tangent",
    NORMAL_CONVENTION,
)
#: A tangent-space normal points out of its surface, so z follows from x and y, and the renderer
#: rebuilds it where it uploads, in arithmetic that enters no digest.
NORMAL_XY: Final = TextureMap(
    "normal",
    2,
    ("normal_x", "normal_y"),
    False,
    "x = 2 * b / 255 - 1, and y likewise; z = sqrt(max(0, 1 - x * x - y * y)); then normalise",
    "tangent",
    NORMAL_CONVENTION,
)
ORM: Final = TextureMap(
    "orm",
    3,
    ("occlusion", "roughness", "metalness"),
    False,
    "b / 255, linear; occlusion 255 is unoccluded; roughness is perceptual",
    None,
    None,
)
TRANSMISSION_ROUGHNESS: Final = TextureMap(
    "transmission_roughness",
    2,
    ("transmission", "roughness"),
    False,
    "b / 255, linear; transmission 255 passes all the light the surface does not reflect; "
    "roughness is perceptual",
    None,
    None,
)
HEIGHT: Final = TextureMap(
    "height",
    1,
    ("height",),
    False,
    "mm = b * height_range_mm / 255, above the lowest point the set can hold",
    None,
    None,
)

#: ``exulanica.texture-set/v1``: the only v1 layout, and every v1 set is ``opaque``.
V1_LAYOUT: Final = (BASE_COLOR, NORMAL_XYZ, ORM, HEIGHT)

#: Every key a v2 header holds whatever its class and maker.
V2_HEADER_KEYS: Final = frozenset(
    {
        "class",
        "extent_mm",
        "family",
        "generator",
        "layout",
        "licence",
        "maker_kind",
        "maps",
        "material_class",
        "media_type",
        "parameters",
        "placement",
        "profile",
        "resolution",
        "seed",
        "set_id",
        "summary",
        "tiling",
        "title",
        "truth",
        "version",
    }
)


def class_layout(
    material_class: str, maker_kind: str, *, normal: bool, height: bool
) -> tuple[TextureMap, ...]:
    """The one layout a v2 container of this class and maker kind holds.

    ``normal`` and ``height`` say which of those maps a model produced; a procedural maker has no
    say, and its layout ignores them.
    """
    colour = BASE_COLOR_COVERAGE if material_class in ("cutout", "decal") else BASE_COLOR
    surface = TRANSMISSION_ROUGHNESS if material_class == "glazing" else ORM
    if maker_kind == "procedural":
        return (
            (BASE_COLOR, TRANSMISSION_ROUGHNESS)
            if material_class == "glazing"
            else (
                colour,
                NORMAL_XY,
                ORM,
            )
        )
    return (
        colour,
        *((NORMAL_XYZ,) if normal else ()),
        surface,
        *((HEIGHT,) if height else ()),
    )


def allowed_channels(
    container_profile: str, material_class: str
) -> tuple[list[dict[str, Any]], ...]:
    """Every layout a container of this profile and class may hold, as manifest channels.

    A manifest entry names no maker kind, so it may list the procedural layout or any model-made
    one; the container's own header then says which it is, and must agree.
    """
    if container_profile == TEXTURE_SET_PROFILE_V1:
        return (
            ([texture_map.as_channel() for texture_map in V1_LAYOUT],)
            if (material_class == "opaque")
            else ()
        )
    layouts = [class_layout(material_class, "procedural", normal=False, height=False)]
    layouts += [
        class_layout(material_class, "model", normal=normal, height=height)
        for normal in (False, True)
        for height in (False, True)
    ]
    unique: list[tuple[TextureMap, ...]] = []
    for layout in layouts:
        if layout not in unique:
            unique.append(layout)
    return tuple([texture_map.as_channel() for texture_map in layout] for layout in unique)


def relief_keys(material_class: str, maker_kind: str, *, ships_height: bool) -> frozenset[str]:
    """The keys a v2 header holds beyond :data:`V2_HEADER_KEYS`.

    A procedural set whose class bakes a height field states the field's range and how its cavity
    was measured, because its normals and occlusion were derived from them; a model-made set states
    the range only when it ships the height map that range decodes.
    """
    if maker_kind == "procedural":
        return (
            frozenset({"cavity", "height_range_mm"})
            if material_class in RELIEF_CLASSES
            else (frozenset())
        )
    return frozenset({"height_range_mm"}) if ships_height else frozenset()


def coverage_permille(colour_coverage: bytes | memoryview) -> int:
    """The share of texels whose coverage is at least :data:`ALPHA_CUTOFF`, in thousandths, floored.

    ``colour_coverage`` is a ``base_color_coverage`` map, four bytes a texel.
    """
    coverage = bytes(memoryview(colour_coverage)[3::4])
    uncovered = sum(coverage.count(value) for value in range(ALPHA_CUTOFF))
    return (len(coverage) - uncovered) * 1000 // len(coverage)


@dataclass(frozen=True, slots=True)
class GlazingFilm:
    """What a glazing set's film is where it covers the glass completely.

    A person names both values, so both are recipe controls, and the header declares them so a
    renderer can lay more of the same film where a pane collects dirt by position, which a tiling
    set cannot know. A reader checks their shape and range and never recomputes them.
    """

    srgb: tuple[int, int, int]
    roughness_permille: int


def _is_int_in(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def declared_film(stated: object) -> GlazingFilm | None:
    """The film a glazing header's ``class`` object declares, or None when it is out of shape.

    ``film_srgb`` is three integers from 0 to 255 and ``film_roughness_permille`` an integer from 0
    to 1000; ``True`` is not an integer here.
    """
    if not isinstance(stated, dict):
        return None
    srgb, roughness = stated.get("film_srgb"), stated.get("film_roughness_permille")
    if not (
        isinstance(srgb, list)
        and len(srgb) == 3
        and all(_is_int_in(channel, 0, 255) for channel in srgb)
        and _is_int_in(roughness, 0, 1000)
    ):
        return None
    return GlazingFilm(srgb=(srgb[0], srgb[1], srgb[2]), roughness_permille=roughness)


def class_parameters(
    material_class: str, coverage: int | None, film: GlazingFilm | None = None
) -> dict[str, Any]:
    """What a header states under ``class``.

    That is the numbers a class fixes, the one a bake measures, and for glazing the film its recipe
    declares.
    """
    if (film is not None) != (material_class == "glazing"):
        raise ValueError(
            f"a {material_class} set {'declares its film' if film is None else 'declares no film'}"
        )
    if film is not None:
        return {
            "double_sided": False,
            "film_roughness_permille": film.roughness_permille,
            "film_srgb": list(film.srgb),
            "ior_millionths": GLAZING_IOR_MILLIONTHS,
        }
    if material_class == "opaque":
        return {}
    if coverage is None:
        raise ValueError(f"a {material_class} set states the coverage its bake measured")
    if material_class == "cutout":
        return {"alpha_cutoff": ALPHA_CUTOFF, "coverage_permille": coverage, "double_sided": True}
    return {"coverage_permille": coverage}
