"""Style packs: the data object that decides how a world looks, read and checked on the server.

A pack is a manifest (``exulanica.style-pack/v1``) and the files it lists. It states a world's
light (named presets of sky, fog, sun and finish), a shading model, the ground beyond the world, a
palette, and what dresses each look role (``family.leaf``): a surface material for the surface
families, and pieces (``exulanica.static-glb/v1`` containers) for the module families. A pack never
states structure, so choosing or changing one cannot move a world's topology.

This is the authoritative reader. The browser's (``web/packages/atlas-core/src/style-pack.ts``) is a
second implementation written from the same rules, and the shared case file
``assets/style-packs/manifest-cases.v1.json`` holds both to the same verdict on every case: the same
first refusal by reason and path, or the same canonical digest. Checks run in one fixed order (each
field in the order the schema lists it, then the cross-section rules), which is why both name the
same first fault.

INTEGERS ONLY. Every number is a whole number in a stated unit, and a manifest's identity is the
SHA-256 of its canonical bytes (keys sorted, no whitespace, ASCII with lowercase ``\\u`` escapes),
which Python and JavaScript write identically.

WHAT IS INJECTED. Look families and their dressing come from the world kinds' catalog; texture set
ids from the texture manifest. :func:`load_context` reads both from the tree.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any, Final, NoReturn

from exulanica_pieces.budgets import BUDGETS_PROFILE, PieceBudget, read_budgets

from exulanica.world.style_pack_preview import PreviewRefused, walk_preview

__all__ = [
    "BUDGETS_PROFILE",
    "COLOUR_ENCODING",
    "EXTENSION_MEDIA_TYPES",
    "IMAGE_MEDIA_TYPES",
    "OWN_WORK",
    "PACK_IMAGES_MAX",
    "PREVIEW_MAX_BYTES",
    "PROFILE",
    "TEXTURE_IMAGE_MAX_BYTES",
    "TEXTURE_IMAGE_MEDIA_TYPES",
    "LookFamily",
    "LookFamilyCatalog",
    "PackImage",
    "PieceBudget",
    "StylePackContext",
    "StylePackRefused",
    "canonical_json",
    "check_pack_images",
    "context_for_manifest",
    "is_plain_text",
    "load_context",
    "manifest_sha256",
    "probe_pack_image",
    "read_manifest",
    "read_piece_budgets",
    "require_chain_catalog",
    "role_offer",
    "split_look_role",
]

PROFILE: Final = "exulanica.style-pack/v1"
COLOUR_ENCODING: Final = "exulanica.srgb8-linear16/v1"
#: A person's own work, kept for their own workspace: the licence id the things record reads as
#: never public (``exulanica.things.origin.OWN_WORK``). Only an uploaded pack may state it.
OWN_WORK: Final = "LicenseRef-Exulanica-Own-Work"
LICENCES: Final = ("CC0-1.0", "CC-BY-4.0", OWN_WORK)
ORIGINS: Final = ("authored", "uploaded", "drafted", "generated", "imported")
#: The pictures a pack may carry, as its one preview: what it looks like, for a person choosing.
IMAGE_MEDIA_TYPES: Final = ("image/jpeg", "image/png", "image/webp")
MEDIA_TYPES: Final = ("model/gltf-binary", *IMAGE_MEDIA_TYPES)
#: The media type each listed file's extension must state.
EXTENSION_MEDIA_TYPES: Final = {
    "glb": "model/gltf-binary",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
#: A pack's preview picture, at most.
PREVIEW_MAX_BYTES: Final = 512 * 1024
#: The pictures a pack may draw with: its own textures and the images its pieces embed. WebP stays
#: the preview's alone.
TEXTURE_IMAGE_MEDIA_TYPES: Final = ("image/jpeg", "image/png")
#: One texture image, at most. Its side is held to the picture walk's own bound (2,048 pixels).
TEXTURE_IMAGE_MAX_BYTES: Final = 4 * 1024 * 1024
#: The images one pack may draw with, its textures' and its pieces' together.
PACK_IMAGES_MAX: Final = 64
#: The textures one pack may carry.
MAX_TEXTURES: Final = 32
TONE_MAPPINGS: Final = ("aces", "aces2", "neutral", "filmic", "linear")
#: The sun shadow filters a pack may choose. PCSS soft shadows are not among them: measured at 26
#: to 27 ms a frame on its own, it alone breaks the frame budget, so it stays a quality setting a
#: person chooses in the render look, never one a pack declares.
SHADOW_FILTERS: Final = ("pcf1", "pcf3", "pcf5")
SHADING_MODELS: Final = ("pbr", "toon", "flat")
MAX_TOTAL_BYTES: Final = 64 * 1024 * 1024
MAX_SWATCHES: Final = 64
MAX_VARIANTS: Final = 8
MAX_PRESETS: Final = 6
MAX_FILES: Final = 512
#: The faces of a building's box a climb rule may grow on, as its slot faces them.
CLIMB_WALLS: Final = ("front", "back", "left", "right")

_PACK_ID: Final = re.compile(r"[a-z][a-z0-9-]{0,31}(\.[a-z][a-z0-9-]{0,31}){1,3}")
_KEY: Final = re.compile(r"[a-z][a-z0-9_]{0,31}")
_TAG: Final = re.compile(r"[a-z][a-z0-9-]{0,23}")
_LEAF: Final = re.compile(r"[a-z][a-z0-9_]{0,47}")
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_PATH: Final = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}(/[a-z0-9][a-z0-9_.-]{0,63}){0,3}\.glb")
_IMAGE_PATH: Final = re.compile(
    r"[a-z0-9][a-z0-9_-]{0,63}(/[a-z0-9][a-z0-9_.-]{0,63}){0,3}\.(jpg|png|webp)"
)
_FILE_PATH: Final = re.compile(
    r"[a-z0-9][a-z0-9_-]{0,63}(/[a-z0-9][a-z0-9_.-]{0,63}){0,3}\.(glb|jpg|png|webp)"
)
_TEXTURE_SET: Final = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}")
#: C0 controls, DEL and C1 controls.
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")
#: The Unicode Bidi_Control characters: marks, embeddings, overrides and isolates, which can make
#: text read in an order other than the one it is stored in.
_BIDI_CONTROL: Final = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
#: A surrogate code point on its own: JSON can escape one, but it is no character, and no UTF-8
#: or UTF-16 encoder writes it.
_SURROGATE: Final = re.compile("[\ud800-\udfff]")
#: The largest whole number both readers hold exactly (JavaScript's Number.MAX_SAFE_INTEGER).
_SAFE_INTEGER: Final = 2**53 - 1
_TEXT_MAX: Final = {
    "title": 80,
    "description": 400,
    "author": 120,
    "attribution": 400,
    "reference": 400,
    "model": 200,
    "prompt": 120,
}


class StylePackRefused(ValueError):
    """A manifest refused by name: the reason, and the path of the first fault."""

    def __init__(self, reason: str, path: str, detail: str) -> None:
        self.reason = reason
        self.path = path
        super().__init__(f"{path or 'manifest'}: {detail}")


@dataclass(frozen=True, slots=True)
class LookFamily:
    fit: str
    dressing: str
    fill_minimum_permille: int
    fill_maximum_permille: int


@dataclass(frozen=True, slots=True)
class LookFamilyCatalog:
    sha256: str
    families: Mapping[str, LookFamily]


@dataclass(frozen=True, slots=True)
class StylePackContext:
    families: Mapping[str, LookFamily]
    texture_sets: frozenset[str]
    family_catalogs: Mapping[int, LookFamilyCatalog] = dataclass_field(default_factory=dict)
    legacy_families: Mapping[str, LookFamily] | None = None


Reader = Callable[[Any, str], Any]


@dataclass(frozen=True, slots=True)
class _Optional:
    """A field a manifest may leave out.

    A field added within a profile is optional and its absence keeps the meaning a manifest had
    before the field existed, so every manifest written under the profile still reads. A manifest
    that leaves it out is returned without it, as given, so its bytes and digest are its own; a
    reader of the result takes the absence as that earlier meaning.
    """

    read: Reader


def _fail(reason: str, path: str, detail: str) -> NoReturn:
    raise StylePackRefused(reason, path, detail)


def _join(path: str, key: str) -> str:
    return key if path == "" else f"{path}.{key}"


def _object(value: Any, path: str, fields: Mapping[str, Reader | _Optional]) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("shape", path, "must be an object")
    for key in value:
        if key not in fields:
            _fail("shape", path, f"has an unknown key {json.dumps(key)}")
    out: dict[str, Any] = {}
    for key, field in fields.items():
        if key not in value:
            if isinstance(field, _Optional):
                continue
            _fail("shape", path, f"is missing {json.dumps(key)}")
        read = field.read if isinstance(field, _Optional) else field
        out[key] = read(value[key], _join(path, key))
    return out


def _integer(minimum: int, maximum: int) -> Reader:
    def read(value: Any, path: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            _fail("shape", path, "must be a whole number")
        if value < minimum or value > maximum:
            _fail("range", path, f"must be within {minimum} to {maximum}")
        return int(value)

    return read


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail("shape", path, "must be true or false")
    return bool(value)


def _one_of(values: tuple[str, ...]) -> Reader:
    def read(value: Any, path: str) -> str:
        if not isinstance(value, str) or value not in values:
            _fail("range", path, f"must be one of {', '.join(values)}")
        return str(value)

    return read


def _literal(expected: str) -> Reader:
    def read(value: Any, path: str) -> str:
        if value != expected or not isinstance(value, str):
            _fail("shape", path, f"must be {json.dumps(expected)}")
        return expected

    return read


def _pattern(regex: re.Pattern[str], what: str) -> Reader:
    def read(value: Any, path: str) -> str:
        if not isinstance(value, str) or regex.fullmatch(value) is None:
            _fail("shape", path, f"must be {what}")
        return str(value)

    return read


def _text(maximum: int, *, allow_empty: bool = False) -> Reader:
    def read(value: Any, path: str) -> str:
        if not isinstance(value, str):
            _fail("shape", path, "must be text")
        # No leading or trailing space, and no control character: the same rule in every reader.
        if value.startswith(" ") or value.endswith(" ") or (not allow_empty and value == ""):
            _fail("shape", path, "must be trimmed text, not empty")
        if _SURROGATE.search(value):
            _fail("shape", path, "must hold no lone surrogate")
        # JavaScript counts UTF-16 code units; count the same here.
        if len(value.encode("utf-16-le")) // 2 > maximum:
            _fail("range", path, f"must be at most {maximum} characters")
        if _CONTROL.search(value):
            _fail("shape", path, "must hold no control characters")
        if _BIDI_CONTROL.search(value):
            _fail("shape", path, "must hold no bidirectional control characters")
        return str(value)

    return read


def is_plain_text(value: str, maximum: int) -> bool:
    """Whether ``value`` meets the readers' text rule: trimmed, not empty, at most ``maximum``
    UTF-16 units, and no lone surrogate, control or bidirectional control character."""
    try:
        _text(maximum)(value, "")
    except StylePackRefused:
        return False
    return True


def _nullable(read: Reader) -> Reader:
    def wrapped(value: Any, path: str) -> Any:
        return None if value is None else read(value, path)

    return wrapped


def _srgb8(value: Any, path: str) -> list[int]:
    if not isinstance(value, list) or len(value) != 3:
        _fail("shape", path, "must be three sRGB bytes")
    return [_integer(0, 255)(channel, f"{path}[{index}]") for index, channel in enumerate(value)]


def _list(read: Reader, minimum: int, maximum: int) -> Reader:
    def wrapped(value: Any, path: str) -> list[Any]:
        if not isinstance(value, list):
            _fail("shape", path, "must be a list")
        if len(value) < minimum or len(value) > maximum:
            _fail("range", path, f"must hold {minimum} to {maximum} items")
        return [read(item, f"{path}[{index}]") for index, item in enumerate(value)]

    return wrapped


def _record(read_key: Callable[[str, str], None], read: Reader, maximum: int) -> Reader:
    def wrapped(value: Any, path: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            _fail("shape", path, "must be an object")
        if len(value) > maximum:
            _fail("range", path, f"must hold at most {maximum} entries")
        out: dict[str, Any] = {}
        for key, item in value.items():
            read_key(key, _join(path, key))
            out[key] = read(item, _join(path, key))
        return out

    return wrapped


def _face_texels(value: Any, path: str) -> int:
    texels = _integer(64, 256)(value, path)
    if texels not in (64, 128, 256):
        _fail("range", path, "must be one of 64, 128, 256")
    return texels


def _fog(value: Any, path: str) -> dict[str, Any]:
    kind = value.get("kind") if isinstance(value, dict) else None
    if kind == "linear":
        fog = _object(
            value,
            path,
            {
                "kind": _literal("linear"),
                "start_mm": _integer(40_000, 60_000),
                "end_mm": _integer(61_000, 4_000_000),
                "colour": _srgb8,
            },
        )
        if fog["end_mm"] <= fog["start_mm"]:
            _fail("range", path, "end_mm must lie beyond start_mm")
        return fog
    if kind == "exp2":
        return _object(
            value,
            path,
            {"kind": _literal("exp2"), "density_micro": _integer(100, 6000), "colour": _srgb8},
        )
    return _fail("range", _join(path, "kind"), "must be one of linear, exp2")


def _sun(value: Any, path: str) -> dict[str, Any]:
    sun = _object(
        value,
        path,
        {
            "elevation_mdeg": _integer(5000, 85_000),
            "azimuth_mdeg": _integer(0, 360_000),
            "colour": _srgb8,
            "intensity_permille": _integer(0, 10_000),
            "shadow": lambda s, q: _object(s, q, {"filter": _one_of(SHADOW_FILTERS)}),
        },
    )
    return sun


def _sky_model(value: Any, path: str) -> dict[str, Any]:
    # How the sky's colour is computed when a preset names a model; the gradient fields stay
    # required beside it for the ground below the horizon.
    kind = value.get("kind") if isinstance(value, dict) else None
    if kind == "analytic":
        return _object(
            value,
            path,
            {
                "kind": _literal("analytic"),
                "turbidity_permille": _integer(1000, 20_000),
                "rayleigh_permille": _integer(0, 4000),
                "mie_micro": _integer(0, 100_000),
                "mie_direction_permille": _integer(0, 950),
            },
        )
    return _fail("range", _join(path, "kind"), "must be one of analytic")


def _haze(value: Any, path: str) -> dict[str, Any]:
    # Haze thinning with height, in place of the preset's fog when stated.
    return _object(
        value,
        path,
        {
            "density_micro": _integer(1, 6000),
            "falloff_micro": _integer(100, 50_000),
            "base_mm": _integer(-50_000, 50_000),
            "max_depth_permille": _integer(1, 8000),
            "colour": _nullable(_srgb8),
        },
    )


def _water(value: Any, path: str) -> dict[str, Any]:
    # How a water surface is finished: colour by depth, what it absorbs, its foam and reflection.
    def absorption(v: Any, p: str) -> list[int]:
        if not isinstance(v, list) or len(v) != 3:
            _fail("shape", p, "must be three absorptions per kilometre")
        return [_integer(0, 5000)(n, f"{p}[{i}]") for i, n in enumerate(v)]

    def drift(v: Any, p: str) -> list[int]:
        if not isinstance(v, list) or len(v) != 2:
            _fail("shape", p, "must be a drift along the octave's two axes in millimetres a second")
        return [_integer(-5000, 5000)(n, f"{p}[{i}]") for i, n in enumerate(v)]

    def octave(v: Any, p: str) -> dict[str, Any]:
        return _object(
            v,
            p,
            {
                "angle_mdeg": _integer(0, 359_999),
                "cell_mm": _integer(100, 20_000),
                "tilt_permille": _integer(0, 200),
                "drift_mm_per_s": drift,
            },
        )

    def ripples(v: Any, p: str) -> dict[str, Any]:
        read = _object(
            v,
            p,
            {
                "octaves": _list(octave, 1, 4),
                "fade_from_millicells_per_px": _integer(10, 2000),
                "fade_to_millicells_per_px": _integer(20, 4000),
            },
        )
        if read["fade_to_millicells_per_px"] <= read["fade_from_millicells_per_px"]:
            _fail("range", f"{p}.fade_to_millicells_per_px", "must be above the fade's start")
        return read

    def caustics(v: Any, p: str) -> dict[str, Any]:
        return _object(
            v,
            p,
            {
                "strength_permille": _integer(0, 2000),
                "cell_mm": _integer(100, 10_000),
                "pace_millirad_per_s": _integer(0, 10_000),
                "reach_mm": _integer(100, 10_000),
            },
        )

    def contact(v: Any, p: str) -> dict[str, Any]:
        # Where the water meets what stands in it and lies under it: how much light a surface under
        # the water keeps, how far light travels down to it per metre of depth, how much the shallow
        # colour needs a surface turned up to the sky, and how far across the surface foam reaches
        # from a solid, by the water's look role (each a water role, checked with the whole pack).
        return _object(
            v,
            p,
            {
                "wet_keep_permille": _integer(0, 1000),
                "light_down_permille": _integer(0, 4000),
                "shallow_facing_permille": _integer(0, 1000),
                "foam_reach_mm": _record(lambda key, kp: None, _integer(100, 5000), 16),
            },
        )

    return _object(
        value,
        path,
        {
            "shallow": _srgb8,
            "deep": _srgb8,
            "absorption_per_km": absorption,
            "depth_scale_mm": _integer(500, 50_000),
            "foam_width_mm": _integer(0, 2000),
            "reflection_permille": _integer(0, 2000),
            # Added within the profile: absent, the ripple is today's and there are no caustics.
            "ripples": _Optional(ripples),
            "caustics": _Optional(caustics),
            # Added within the profile: absent, the water meets solids as it always has.
            "contact": _Optional(contact),
        },
    )


def _wind(value: Any, path: str) -> dict[str, Any]:
    # The wind a preset's plants sway in: its direction, sway, pace, gusts and flutter, and which
    # families sway. Absent, nothing sways.
    def families(v: Any, p: str) -> list[str]:
        return _list(_pattern(_KEY, "a look family"), 1, 8)(v, p)

    return _object(
        value,
        path,
        {
            "direction_mdeg": _integer(0, 359_999),
            "sway_mm": _integer(0, 2000),
            "pace_millirad_per_s": _integer(0, 20_000),
            "gust_scale_mm": _integer(1000, 200_000),
            "gust_share_permille": _integer(0, 1000),
            "flutter_mm": _integer(0, 200),
            "sway_families": families,
        },
    )


def _falling_water(value: Any, path: str) -> dict[str, Any]:
    # How a sheet of falling water is finished: streaks moving down it, and foam where it lands.
    return _object(
        value,
        path,
        {
            "streak_speed_mm_per_s": _integer(200, 20_000),
            "streak_width_mm": _integer(20, 2000),
            "streak_length_mm": _integer(100, 20_000),
            "streak_contrast_permille": _integer(0, 1000),
            "aeration_permille": _integer(0, 1000),
            "foam_height_mm": _integer(0, 5000),
            "foam": _srgb8,
        },
    )


def _light_preset(value: Any, path: str) -> dict[str, Any]:
    clouds = _nullable(
        lambda c, q: _object(
            c,
            q,
            {
                "cover_permille": _integer(0, 1000),
                "colour": _srgb8,
                "shade": _srgb8,
                "scale_permille": _integer(250, 4000),
                "seed": _integer(0, 2_147_483_647),
            },
        )
    )
    sky = {
        "zenith": _srgb8,
        "horizon": _srgb8,
        "ground": _srgb8,
        "bounce_ground": _srgb8,
        "intensity_permille": _integer(250, 4000),
        "sun_glow_permille": _integer(0, 2000),
        "sun_disc_permille": _integer(0, 64_000),
        "clouds": clouds,
        "face_texels": _face_texels,
        # Added within the profile: a preset written before it draws the gradient sky.
        "model": _Optional(_sky_model),
    }
    post = {
        "bloom": _nullable(
            lambda b, q: _object(
                b, q, {"intensity_permille": _integer(0, 200), "blur_level": _integer(1, 16)}
            )
        ),
        "grading": lambda g, q: _object(
            g,
            q,
            {
                "brightness_permille": _integer(500, 1500),
                "contrast_permille": _integer(500, 1500),
                "saturation_permille": _integer(0, 2000),
                "tint": _srgb8,
            },
        ),
        "enhance": lambda e, q: _object(
            e,
            q,
            {
                "shadows_permille": _integer(-1000, 1000),
                "highlights_permille": _integer(-1000, 1000),
                "midtones_permille": _integer(-1000, 1000),
                "vibrance_permille": _integer(-1000, 1000),
                "dehaze_permille": _integer(-1000, 1000),
            },
        ),
        "vignette": _nullable(
            lambda v, q: _object(
                v,
                q,
                {
                    "intensity_permille": _integer(0, 1000),
                    "inner_permille": _integer(0, 1500),
                    "outer_permille": _integer(0, 2000),
                    "curvature_permille": _integer(100, 10_000),
                    "colour": _srgb8,
                },
            )
        ),
        "taa": _boolean,
        # Added within the profile: absent, the frame is not sharpened, as before.
        "sharpness_permille": _Optional(_integer(0, 1000)),
    }
    return _object(
        value,
        path,
        {
            "exposure_permille": _integer(250, 4000),
            "tone_mapping": _one_of(TONE_MAPPINGS),
            "sky": lambda v, p: _object(v, p, sky),
            "fog": _fog,
            "sun": _sun,
            "environment": lambda v, p: _object(v, p, {"intensity_permille": _integer(50, 4000)}),
            "contact_shadow": lambda v, p: _object(
                v,
                p,
                {
                    "mode": _one_of(("lighting", "combine")),
                    "radius_mm": _integer(100, 3000),
                    "intensity_permille": _integer(50, 1000),
                },
            ),
            "post": lambda v, p: _object(v, p, post),
            # Added within the profile: a preset written before it draws its fog.
            "haze": _Optional(_haze),
            # Added within the profile: a preset written before it holds every plant still.
            "wind": _Optional(_wind),
            # Added within the profile: absent, each facade's windows are lit by its sun.
            "lit_windows_permille": _Optional(_integer(0, 1000)),
        },
    )


def _provenance(value: Any, path: str) -> dict[str, Any]:
    kind = value.get("kind") if isinstance(value, dict) else None
    sha = _pattern(_SHA256, "a lowercase SHA-256")
    if kind in ("authored", "uploaded"):
        return _object(value, path, {"kind": _literal(str(kind))})
    if kind == "drafted":
        return _object(
            value,
            path,
            {
                "kind": _literal("drafted"),
                "model_id": _text(_TEXT_MAX["model"]),
                "prompt_version": _text(_TEXT_MAX["prompt"]),
                "execution_id": _text(_TEXT_MAX["prompt"]),
                "words_sha256": sha,
            },
        )
    if kind == "generated":
        return _object(value, path, {"kind": _literal("generated"), "receipts": _list(sha, 1, 512)})
    if kind == "imported":
        return _object(
            value,
            path,
            {"kind": _literal("imported"), "source_reference": _text(_TEXT_MAX["reference"])},
        )
    return _fail("range", _join(path, "kind"), f"must be one of {', '.join(ORIGINS)}")


def split_look_role(role: str, path: str) -> tuple[str, str]:
    """A look role's family and leaf, or a refusal naming the role."""
    family, dot, leaf = role.partition(".")
    if not dot or _KEY.fullmatch(family) is None or _LEAF.fullmatch(leaf) is None:
        _fail("shape", path, f"{json.dumps(role)} is not a look role family.leaf")
    return family, leaf


def _catalog_pin(value: Any, path: str, context: StylePackContext) -> dict[str, Any]:
    pin = _object(
        value,
        path,
        {
            "version": _integer(1, 1_000_000),
            "sha256": _pattern(_SHA256, "a lowercase SHA-256"),
        },
    )
    known = context.family_catalogs.get(pin["version"])
    if known is None:
        _fail("reference", _join(path, "version"), "names no retained look-family catalog")
    if known.sha256 != pin["sha256"]:
        _fail("reference", _join(path, "sha256"), "does not match the retained catalog bytes")
    return pin


def context_for_manifest(
    manifest: Mapping[str, Any], context: StylePackContext
) -> StylePackContext:
    """Select only a retained appearance catalog, preserving legacy semantics when absent.

    The digest is of the retained file's exact bytes. No manifest may supply a path or URL.
    Selection does not change a kind's catalog or canonical drawing.
    """
    legacy = context.families if context.legacy_families is None else context.legacy_families
    if "look_family_catalog" not in manifest:
        return replace(context, families=legacy, legacy_families=legacy)
    pin = _catalog_pin(manifest["look_family_catalog"], "look_family_catalog", context)
    return replace(
        context, families=context.family_catalogs[pin["version"]].families, legacy_families=legacy
    )


def require_chain_catalog(chain: Sequence[Mapping[str, Any]]) -> None:
    """A chain shares one explicit pin, or every manifest keeps the legacy absence.

    Catalog selection is not inherited: an unpinned child cannot reinterpret a pinned base,
    nor can a pinned child reinterpret historical pieces from an unpinned base.
    """
    if chain and any(
        manifest.get("look_family_catalog") != chain[0].get("look_family_catalog")
        for manifest in chain[1:]
    ):
        _fail("reference", "base", "every manifest of a chain must select the same look catalog")


def role_offer(
    chain: Sequence[Mapping[str, Any]], role: str, context: StylePackContext
) -> str | None:
    """What a pack offers ``role`` before any slot's fit: ``leaf`` when a manifest of ``chain``
    (the pack, then its bases, nearest first) dresses the role itself, ``default`` when only its
    family's ``default`` leaf is dressed, None when the page draws the engine's primitive. The
    order is the page's ``resolveLookRole`` (``web/packages/atlas-core/src/style-pack.ts``): the
    leaf, then the family's default, a surface or a module as the family takes. A slot's size can
    still pass a dressed role to the primitive at draw time; this is the question a role asks of a
    look."""
    require_chain_catalog(chain)
    if chain:
        context = context_for_manifest(chain[0], context)
    family, leaf = split_look_role(role, "role")
    kind = context.families.get(family)
    if kind is None:
        return None
    surfaces = kind.dressing in ("surface", "both")
    modules = kind.dressing in ("module", "both")
    candidates = [(role, "leaf")]
    if leaf != "default":
        candidates.append((f"{family}.default", "default"))
    for name, offer in candidates:
        for manifest in chain:
            if (surfaces and name in manifest["surfaces"]) or (
                modules and name in manifest["modules"]
            ):
                return offer
    return None


def read_manifest(value: Any, context: StylePackContext) -> dict[str, Any]:
    """Read a manifest, or refuse it with the first rule it breaks, by reason and path."""

    selected = context_for_manifest({}, context)

    def select_catalog(value: Any, path: str) -> dict[str, Any]:
        nonlocal selected
        pin = _catalog_pin(value, path, context)
        selected = context_for_manifest({"look_family_catalog": pin}, context)
        return pin

    def look_role_key(dressings: tuple[str, ...]) -> Callable[[str, str], None]:
        def read(key: str, path: str) -> None:
            family, _leaf = split_look_role(key, path)
            known = selected.families.get(family)
            if known is None:
                _fail("reference", path, f"names no look family {json.dumps(family)}")
            elif known.dressing not in dressings:
                _fail("reference", path, f"family {json.dumps(family)} is not dressed this way")

        return read

    def piece_role(value: Any, path: str) -> str:
        if not isinstance(value, str):
            _fail("shape", path, "must be a look role")
        look_role_key(("module", "both"))(value, path)
        return value

    def cover(value: Any, path: str) -> dict[str, Any]:
        def scale(v: Any, p: str) -> list[int]:
            if not isinstance(v, list) or len(v) != 2:
                _fail("shape", p, "must be a least and a most scale in thousandths")
            read = [_integer(100, 3000)(n, f"{p}[{i}]") for i, n in enumerate(v)]
            if read[0] > read[1]:
                _fail("range", p, "must not have its least above its most")
            return read

        return _object(
            value,
            path,
            {
                "pieces": _list(piece_role, 1, 8),
                "density_per_100m2": _integer(1, 4000),
                "scale_permille": scale,
                "seed": _integer(0, 2_147_483_647),
            },
        )

    def facade(value: Any, path: str) -> dict[str, Any]:
        # The windows a wall look role's building walls are drawn with: storeys, bays, one window
        # size, trims, glass, the lamps behind them and how many are lit by the sun.
        def window(v: Any, p: str) -> list[int]:
            if not isinstance(v, list) or len(v) != 2:
                _fail("shape", p, "must be a width and a height in millimetres")
            return [_integer(300, 19_000)(v[0], f"{p}[0]"), _integer(300, 10_000)(v[1], f"{p}[1]")]

        read = _object(
            value,
            path,
            {
                "storey_mm": _integer(2000, 12_000),
                "bay_mm": _integer(600, 20_000),
                "window_mm": window,
                "sill_mm": _integer(0, 3000),
                "head_mm": _integer(0, 3000),
                "clear_storeys": _integer(0, 20),
                "room_bays": _integer(1, 8),
                "reveal_mm": _integer(0, 600),
                "reveal_shade_permille": _integer(0, 1000),
                "ledge_mm": _integer(0, 300),
                "ledge_light_permille": _integer(0, 1000),
                "glass_darkening_permille": _integer(0, 1000),
                "glass_gloss_permille": _integer(0, 1000),
                "lit_day_permille": _integer(0, 1000),
                "lit_dusk_permille": _integer(0, 1000),
                "day_sun_mdeg": _integer(5000, 85_000),
                "dusk_sun_mdeg": _integer(5000, 85_000),
                "warm": _srgb8,
                "cool": _srgb8,
                "unlit": _srgb8,
                "warm_permille": _integer(0, 1000),
                "lamp_spread_permille": _integer(0, 1000),
                "light_permille": _integer(0, 20_000),
                "room_depth_mm": _integer(500, 30_000),
                "fade_from_millicells_per_px": _integer(10, 4000),
                "fade_to_millicells_per_px": _integer(20, 8000),
            },
        )
        if read["window_mm"][0] >= read["bay_mm"]:
            _fail("range", f"{path}.window_mm", "must be narrower than its bay")
        if read["day_sun_mdeg"] <= read["dusk_sun_mdeg"]:
            _fail("range", f"{path}.day_sun_mdeg", "must lie above dusk_sun_mdeg")
        if read["fade_to_millicells_per_px"] <= read["fade_from_millicells_per_px"]:
            _fail("range", f"{path}.fade_to_millicells_per_px", "must be above the fade's start")
        return read

    def climb(value: Any, path: str) -> dict[str, Any]:
        def walls(v: Any, p: str) -> list[str]:
            read = _list(_one_of(CLIMB_WALLS), 1, len(CLIMB_WALLS))(v, p)
            if len(set(read)) != len(read):
                _fail("duplicate", p, "names a wall twice")
            return read

        def height(v: Any, p: str) -> list[int]:
            if not isinstance(v, list) or len(v) != 2:
                _fail("shape", p, "must be a least and a most share of the building's height")
            read = [_integer(1, 1000)(n, f"{p}[{i}]") for i, n in enumerate(v)]
            if read[0] > read[1]:
                _fail("range", p, "must not have its least above its most")
            return read

        return _object(
            value,
            path,
            {
                "pieces": _list(piece_role, 1, 8),
                "walls": walls,
                "sun_within_mdeg": _Optional(_integer(0, 180_000)),
                "share_permille": _integer(1, 1000),
                "height_permille": height,
                "seed": _integer(0, 2_147_483_647),
            },
        )

    def land_cover_key(key: str, path: str) -> None:
        if _KEY.fullmatch(key) is None:
            _fail("shape", path, "must be a rule key")

    def pair_of(least: int, most: int, says: str) -> Reader:
        # A least and a most within a range, the least not above the most.
        def read(v: Any, p: str) -> list[int]:
            if not isinstance(v, list) or len(v) != 2:
                _fail("shape", p, says)
            read = [_integer(least, most)(n, f"{p}[{i}]") for i, n in enumerate(v)]
            if read[0] > read[1]:
                _fail("range", p, "must not have its least above its most")
            return read

        return read

    def land_cover(value: Any, path: str) -> dict[str, Any]:
        # What grows on the near land where it is drawn in a surface role (`land`, or a band of
        # the land's surface catalog): which plant or prop pieces, how many a hectare, at what
        # sizes, from which seed, optionally within a slope and a height and near the place, and
        # optionally gathered in groves.
        return _object(
            value,
            path,
            {
                "role": _pattern(_KEY, "a land surface role"),
                "pieces": _list(piece_role, 1, 8),
                "density_per_ha": _integer(1, 400_000),
                "scale_permille": pair_of(
                    100, 3000, "must be a least and a most scale in thousandths"
                ),
                "seed": _integer(0, 2_147_483_647),
                "slope_permille": _Optional(
                    pair_of(0, 20_000, "must be a least and a most slope in thousandths")
                ),
                "height_mm": _Optional(
                    pair_of(
                        -10_000_000, 10_000_000, "must be a least and a most height in millimetres"
                    )
                ),
                "within_mm": _Optional(_integer(0, 4_000_000)),
                # Added within the profile: absent, the rule's pieces lie evenly over its land.
                "clump": _Optional(clump),
            },
        )

    def clump(value: Any, path: str) -> dict[str, Any]:
        # Groves: a grove's least and most radius, about the share of the land the groves cover,
        # and the share of the rule's pieces that grow in them (the rest grow between).
        return _object(
            value,
            path,
            {
                "size_mm": pair_of(
                    1000, 200_000, "must be a least and a most grove radius in millimetres"
                ),
                "cover_permille": _integer(1, 999),
                "share_permille": _integer(0, 1000),
            },
        )

    def preset_key(key: str, path: str) -> None:
        if _KEY.fullmatch(key) is None:
            _fail("shape", path, "must be a preset key")

    def surface(value: Any, path: str) -> dict[str, Any]:
        key = _pattern(_KEY, "a swatch key")
        if isinstance(value, dict) and "texture" in value:
            return _object(
                value, path, {"texture": _pattern(_KEY, "a texture key"), "up": _nullable(key)}
            )
        if isinstance(value, dict) and "texture_set" in value:
            return _object(
                value,
                path,
                {
                    "texture_set": _pattern(_TEXTURE_SET, "a texture set id"),
                    "up": _nullable(key),
                },
            )
        return _object(value, path, {"swatch": key, "up": _nullable(key)})

    def texture_key(key: str, path: str) -> None:
        if _KEY.fullmatch(key) is None:
            _fail("shape", path, "must be a texture key")

    image = _pattern(_IMAGE_PATH, "a lowercase relative path ending .jpg or .png")

    def extent(value: Any, path: str) -> list[int]:
        if not isinstance(value, list) or len(value) != 2:
            _fail("shape", path, "must be a width and a height in millimetres")
        return [_integer(100, 50_000)(n, f"{path}[{i}]") for i, n in enumerate(value)]

    def texture(value: Any, path: str) -> dict[str, Any]:
        return _object(
            value,
            path,
            {
                "colour": image,
                "normal": _nullable(image),
                "roughness": _nullable(image),
                "extent_mm": extent,
            },
        )

    def size(value: Any, path: str) -> list[int]:
        if not isinstance(value, list) or len(value) != 3:
            _fail("shape", path, "must be width, depth and height in millimetres")
        return [_integer(1, 50_000)(n, f"{path}[{i}]") for i, n in enumerate(value)]

    def zone(value: Any, path: str) -> list[int]:
        if not isinstance(value, list) or len(value) != 2:
            _fail("shape", path, "must be a low and a high in millimetres")
        return [_integer(0, 50_000)(n, f"{path}[{k}]") for k, n in enumerate(value)]

    def stretch(value: Any, path: str) -> list[list[int] | None]:
        if not isinstance(value, list) or len(value) != 3:
            _fail("shape", path, "must be a zone or null for width, depth and height")
        return [_nullable(zone)(z, f"{path}[{i}]") for i, z in enumerate(value)]

    glb = _pattern(_PATH, "a lowercase relative path ending .glb")
    sha = _pattern(_SHA256, "a lowercase SHA-256")
    pack_id = _pattern(_PACK_ID, "a namespaced id such as exulanica.cozy-town")
    manifest = _object(
        value,
        "",
        {
            "profile": _literal(PROFILE),
            "pack_id": pack_id,
            "version": _integer(1, 1_000_000),
            "title": _text(_TEXT_MAX["title"]),
            "description": _text(_TEXT_MAX["description"], allow_empty=True),
            "tags": _list(_pattern(_TAG, "a lowercase tag"), 0, 12),
            "origin": _one_of(ORIGINS),
            "provenance": _provenance,
            "licence": lambda v, p: _object(
                v,
                p,
                {
                    "id": _one_of(LICENCES),
                    "attribution": _nullable(_text(_TEXT_MAX["attribution"])),
                },
            ),
            "authors": _list(_text(_TEXT_MAX["author"]), 1, 16),
            # Added after the first packs were published: a manifest from before it names none.
            "preview": _Optional(
                _nullable(
                    _pattern(_IMAGE_PATH, "a lowercase relative path ending .jpg, .png or .webp")
                )
            ),
            "base": _nullable(
                lambda v, p: _object(
                    v,
                    p,
                    {
                        "pack_id": pack_id,
                        "version": _integer(1, 1_000_000),
                        "manifest_sha256": sha,
                    },
                )
            ),
            "light": _nullable(
                lambda v, p: _object(
                    v,
                    p,
                    {
                        "default_preset": _pattern(_KEY, "a preset key"),
                        "presets": _record(preset_key, _light_preset, MAX_PRESETS),
                    },
                )
            ),
            "shading": _nullable(
                lambda v, p: _object(
                    v,
                    p,
                    {
                        "model": _one_of(SHADING_MODELS),
                        "toon": _nullable(
                            lambda t, q: _object(
                                t,
                                q,
                                {
                                    "shadow_edge_permille": _integer(0, 1000),
                                    "light_edge_permille": _integer(0, 1000),
                                    "band_share_permille": _integer(0, 1000),
                                    "softness_permille": _integer(5, 200),
                                },
                            )
                        ),
                        "ink": _nullable(_srgb8),
                    },
                )
            ),
            "edge": _nullable(
                lambda v, p: _object(
                    v,
                    p,
                    {
                        "ground": _srgb8,
                        "drop_mm": _integer(200, 5000),
                        "reach_mm": _integer(200_000, 8_000_000),
                    },
                )
            ),
            # Added within the profile: a pack written before it draws water as its surface states.
            "water": _Optional(_water),
            # Added within the profile: a pack written before it has its falling water finished
            # by the page's defaults.
            "falling_water": _Optional(_falling_water),
            "palette": lambda v, p: _object(
                v,
                p,
                {
                    "encoding": _literal(COLOUR_ENCODING),
                    "swatches": _list(
                        lambda s, q: _object(
                            s,
                            q,
                            {
                                "key": _pattern(_KEY, "a swatch key"),
                                "srgb8": _srgb8,
                                "roughness_permille": _integer(0, 1000),
                                "metalness_permille": _integer(0, 1000),
                                "emission_permille": _integer(0, 1000),
                            },
                        ),
                        0,
                        MAX_SWATCHES,
                    ),
                },
            ),
            "look_family_catalog": _Optional(select_catalog),
            "surfaces": _record(look_role_key(("surface", "both")), surface, 256),
            # Added within the profile: a pack that carries no textures of its own names none.
            "textures": _Optional(_record(texture_key, texture, MAX_TEXTURES)),
            # Added within the profile: a pack written before it grows nothing on its grounds.
            "cover": _Optional(_record(look_role_key(("surface", "both")), cover, 64)),
            # Added within the profile: a pack written before it draws no windows on its walls.
            "facade": _Optional(_record(look_role_key(("surface", "both")), facade, 64)),
            # Added within the profile: a pack that grows nothing on its walls states none.
            "climb": _Optional(_record(look_role_key(("module", "both")), climb, 64)),
            # Added within the profile: a pack written before it grows nothing on the land.
            "land_cover": _Optional(_record(land_cover_key, land_cover, 16)),
            "modules": _record(
                look_role_key(("module", "both")),
                lambda v, p: _object(
                    v,
                    p,
                    {
                        "variants": _list(
                            lambda item, q: _object(
                                item,
                                q,
                                {
                                    "file": glb,
                                    "lod1": _nullable(glb),
                                    "size_mm": size,
                                    "stretch_mm": stretch,
                                    # Added within the profile: the share of a wind's sway the
                                    # variant's pieces take; absent, the whole of it.
                                    "sway_permille": _Optional(_integer(0, 4000)),
                                    # Added within the profile: a variant that repeats nothing
                                    # states none.
                                    "repeat_mm": _Optional(stretch),
                                },
                            ),
                            1,
                            MAX_VARIANTS,
                        )
                    },
                ),
                512,
            ),
            "files": _list(
                lambda v, p: _object(
                    v,
                    p,
                    {
                        "path": _pattern(
                            _FILE_PATH, "a lowercase relative path ending .glb, .jpg, .png or .webp"
                        ),
                        "sha256": sha,
                        "bytes": _integer(1, MAX_TOTAL_BYTES),
                        "media_type": _one_of(MEDIA_TYPES),
                    },
                ),
                0,
                MAX_FILES,
            ),
        },
    )
    _check_whole(manifest, selected)
    return manifest


def _check_whole(manifest: dict[str, Any], context: StylePackContext) -> None:
    if manifest["provenance"]["kind"] != manifest["origin"]:
        _fail("reference", "provenance.kind", "must equal the origin")
    licence = manifest["licence"]
    if licence["id"] == "CC-BY-4.0" and licence["attribution"] is None:
        _fail("licence", "licence.attribution", "is required for CC-BY-4.0")
    if licence["id"] == "CC0-1.0" and licence["attribution"] is not None:
        _fail("licence", "licence.attribution", "must be null for CC0-1.0")
    if licence["id"] == OWN_WORK and manifest["origin"] != "uploaded":
        _fail("licence", "licence.id", f"{OWN_WORK} is for an uploaded pack only")
    if licence["id"] == OWN_WORK and licence["attribution"] is not None:
        _fail("licence", "licence.attribution", f"must be null for {OWN_WORK}")
    if manifest["base"] is None and (manifest["light"] is None or manifest["shading"] is None):
        _fail(
            "reference",
            "light" if manifest["light"] is None else "shading",
            "is required in a pack with no base",
        )
    light = manifest["light"]
    if light is not None and light["default_preset"] not in light["presets"]:
        _fail("reference", "light.default_preset", "names no preset")
    shading = manifest["shading"]
    if shading is not None and (shading["model"] == "toon") != (shading["toon"] is not None):
        _fail("reference", "shading.toon", "is stated exactly when the model is toon")
    toon = None if shading is None else shading["toon"]
    if toon is not None and toon["shadow_edge_permille"] >= toon["light_edge_permille"]:
        _fail(
            "range",
            "shading.toon",
            "shadow_edge_permille must lie below light_edge_permille",
        )
    keys: set[str] = set()
    colours: set[tuple[int, ...]] = set()
    for index, swatch in enumerate(manifest["palette"]["swatches"]):
        if swatch["key"] in keys:
            _fail(
                "duplicate",
                f"palette.swatches[{index}].key",
                f"repeats {json.dumps(swatch['key'])}",
            )
        keys.add(swatch["key"])
        colour = tuple(swatch["srgb8"])
        if colour in colours:
            _fail(
                "duplicate",
                f"palette.swatches[{index}].srgb8",
                "repeats a colour another swatch has",
            )
        colours.add(colour)
    for role, surface in manifest["surfaces"].items():
        if "swatch" in surface and surface["swatch"] not in keys:
            _fail(
                "reference",
                f"surfaces.{role}.swatch",
                f"names no swatch {json.dumps(surface['swatch'])}",
            )
        if "texture" in surface and surface["texture"] not in manifest.get("textures", {}):
            _fail(
                "reference",
                f"surfaces.{role}.texture",
                f"names no texture {json.dumps(surface['texture'])}",
            )
        if "texture_set" in surface and surface["texture_set"] not in context.texture_sets:
            _fail(
                "reference",
                f"surfaces.{role}.texture_set",
                f"names no texture set {json.dumps(surface['texture_set'])}",
            )
        if surface["up"] is not None and surface["up"] not in keys:
            _fail(
                "reference", f"surfaces.{role}.up", f"names no swatch {json.dumps(surface['up'])}"
            )
    for role, rule in manifest.get("cover", {}).items():
        for index, piece in enumerate(rule["pieces"]):
            where = f"cover.{role}.pieces[{index}]"
            if split_look_role(piece, where)[0] != "plant":
                _fail("reference", where, "a cover piece is a plant")
            if manifest["base"] is None and piece not in manifest["modules"]:
                _fail("reference", where, f"names no module {json.dumps(piece)}")
    for role in manifest.get("facade", {}):
        if split_look_role(role, f"facade.{role}")[0] != "wall":
            _fail("reference", f"facade.{role}", "a facade is a wall's")
    for role in manifest.get("water", {}).get("contact", {}).get("foam_reach_mm", {}):
        where = f"water.contact.foam_reach_mm.{role}"
        if split_look_role(role, where)[0] != "water":
            _fail("reference", where, "a foam reach is a water's")
    for role, rule in manifest.get("climb", {}).items():
        if split_look_role(role, f"climb.{role}")[0] != "structure":
            _fail("reference", f"climb.{role}", "plants climb only a structure's walls")
        for index, piece in enumerate(rule["pieces"]):
            where = f"climb.{role}.pieces[{index}]"
            if split_look_role(piece, where)[0] != "plant":
                _fail("reference", where, "a climbing piece is a plant")
            if manifest["base"] is None and piece not in manifest["modules"]:
                _fail("reference", where, f"names no module {json.dumps(piece)}")
    for role, rule in manifest.get("land_cover", {}).items():
        for index, piece in enumerate(rule["pieces"]):
            where = f"land_cover.{role}.pieces[{index}]"
            if split_look_role(piece, where)[0] not in ("plant", "prop"):
                _fail("reference", where, "a land cover piece is a plant or a prop")
            if manifest["base"] is None and piece not in manifest["modules"]:
                _fail("reference", where, f"names no module {json.dumps(piece)}")
    for name, preset in (manifest["light"] or {"presets": {}})["presets"].items():
        for index, family in enumerate(preset.get("wind", {}).get("sway_families", [])):
            if family not in context.families:
                _fail(
                    "reference",
                    f"light.presets.{name}.wind.sway_families[{index}]",
                    f"names no look family {json.dumps(family)}",
                )
    listed: dict[str, dict[str, Any]] = {}
    total = 0
    previous: str | None = None
    for index, file in enumerate(manifest["files"]):
        if file["path"] in listed:
            _fail("duplicate", f"files[{index}].path", f"repeats {json.dumps(file['path'])}")
        if previous is not None and _utf16_key(previous) > _utf16_key(file["path"]):
            _fail("shape", f"files[{index}].path", "files must be listed in path order")
        stated = EXTENSION_MEDIA_TYPES[file["path"].rsplit(".", 1)[1]]
        if file["media_type"] != stated:
            _fail("shape", f"files[{index}].media_type", f"must be {stated} for its extension")
        previous = file["path"]
        listed[file["path"]] = file
        total += file["bytes"]
    if total > MAX_TOTAL_BYTES:
        _fail("range", "files", f"must total at most {MAX_TOTAL_BYTES} bytes")
    used: set[str] = set()
    for role, module in manifest["modules"].items():
        for index, variant in enumerate(module["variants"]):
            for field in ("file", "lod1"):
                path = variant[field]
                if path is None:
                    continue
                if path not in listed:
                    _fail(
                        "reference",
                        f"modules.{role}.variants[{index}].{field}",
                        f"names no listed file {json.dumps(path)}",
                    )
                used.add(path)
            where = f"modules.{role}.variants[{index}].stretch_mm"
            family = context.families.get(split_look_role(role, "modules")[0])
            if any(z is not None for z in variant["stretch_mm"]) and (
                family is None or family.fit != "fill"
            ):
                _fail("reference", where, "stretches only a piece of a fill family")
            for axis, z in enumerate(variant["stretch_mm"]):
                if z is not None and not z[0] < z[1] <= variant["size_mm"][axis]:
                    _fail("range", f"{where}[{axis}]", "must lie within the piece, low below high")
            repeat = variant.get("repeat_mm")
            if repeat is not None:
                where = f"modules.{role}.variants[{index}].repeat_mm"
                if any(z is not None for z in repeat) and (family is None or family.fit != "fill"):
                    _fail("reference", where, "repeats only a piece of a fill family")
                for axis, z in enumerate(repeat):
                    if z is None:
                        continue
                    if not z[0] < z[1] <= variant["size_mm"][axis]:
                        _fail(
                            "range", f"{where}[{axis}]", "must lie within the piece, low below high"
                        )
                    if variant["stretch_mm"][axis] is not None:
                        _fail("shape", f"{where}[{axis}]", "an axis stretches or repeats, not both")
    preview = manifest.get("preview")
    if preview is not None:
        if preview not in listed:
            _fail("reference", "preview", f"names no listed file {json.dumps(preview)}")
        used.add(preview)
        if listed[preview]["bytes"] > PREVIEW_MAX_BYTES:
            _fail(
                "range",
                f"files[{list(listed).index(preview)}].bytes",
                f"a picture is at most {PREVIEW_MAX_BYTES} bytes",
            )
    images: set[str] = set()
    for key, texture in manifest.get("textures", {}).items():
        for map_name in ("colour", "normal", "roughness"):
            path = texture[map_name]
            if path is None:
                continue
            where = f"textures.{key}.{map_name}"
            if path not in listed:
                _fail("reference", where, f"names no listed file {json.dumps(path)}")
            if listed[path]["media_type"] not in TEXTURE_IMAGE_MEDIA_TYPES:
                _fail("shape", where, "a texture image is a JPEG or a PNG")
            if listed[path]["bytes"] > TEXTURE_IMAGE_MAX_BYTES:
                _fail("range", where, f"a texture image is at most {TEXTURE_IMAGE_MAX_BYTES} bytes")
            used.add(path)
            images.add(path)
    check_pack_images(len(images))
    for path in listed:
        if path not in used:
            _fail("reference", "files", f"lists {json.dumps(path)}, which nothing uses")


@dataclass(frozen=True, slots=True)
class PackImage:
    """A picture a pack draws with, as the walk read it: its size and the media type it is."""

    width_px: int
    height_px: int
    media_type: str


def probe_pack_image(data: bytes, media_type: str) -> PackImage:
    """Walk a picture a pack draws with to its end (a texture's map, or an image a piece embeds),
    given as raw bytes and the media type it is stated to be. Refused by name: a type that is not
    JPEG or PNG, and every reason the picture walk refuses (:class:`PreviewRefused`)."""
    if media_type not in TEXTURE_IMAGE_MEDIA_TYPES:
        raise PreviewRefused("media_type", "a picture a pack draws with is a JPEG or a PNG")
    size = walk_preview(data, media_type)
    return PackImage(size.width_px, size.height_px, media_type)


def check_pack_images(texture_images: int, embedded_images: int = 0) -> None:
    """Refuse a pack that draws with more pictures than :data:`PACK_IMAGES_MAX`: its textures'
    distinct images and the images its pieces embed, counted together."""
    if texture_images + embedded_images > PACK_IMAGES_MAX:
        _fail(
            "range",
            "files",
            f"draws with {texture_images + embedded_images} pictures; at most {PACK_IMAGES_MAX}",
        )


def _utf16_key(text: str) -> bytes:
    """JavaScript compares strings by UTF-16 code units; so does this."""
    return text.encode("utf-16-be")


def canonical_json(value: Any) -> str:
    """Canonical JSON: keys sorted, no whitespace, ASCII with lowercase escapes, integers only.

    Every number at every depth is a whole number both readers hold exactly, as the browser's
    ``canonicalJson`` requires; a fraction, a non-finite number (which ``json.loads`` reads from
    ``NaN`` and ``Infinity``) or a whole number past 2**53 - 1 is refused by name.
    """
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, float) or (
            isinstance(item, int) and not isinstance(item, bool) and abs(item) > _SAFE_INTEGER
        ):
            raise StylePackRefused("shape", "", "a canonical manifest holds whole numbers only")
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """The manifest's identity: the SHA-256 of its canonical bytes."""
    return hashlib.sha256(canonical_json(manifest).encode("ascii")).hexdigest()


def load_context(root: Path) -> StylePackContext:
    """Legacy families, retained appearance catalogs and texture ids from trusted ``root``.

    Only these explicit retained filenames are registered, never a manifest-supplied path or a
    latest-version glob. The optional v2 and v3 files allow minimal legacy fixture roots to keep
    working.
    """
    catalogs: dict[int, LookFamilyCatalog] = {}
    for version in (1, 2, 3):
        path = root / f"assets/catalogs/world-kinds/look-family.v{version}.json"
        if version > 1 and not path.exists():
            continue
        raw = path.read_bytes()
        catalog = json.loads(raw)
        if catalog["catalog_id"] != "look-family" or catalog["catalog_version"] != version:
            raise ValueError(f"{path}: is not look-family catalog version {version}")
        families = {
            entry["key"]: LookFamily(
                fit=entry["fit"],
                dressing=entry["dressing"],
                fill_minimum_permille=entry["fill_minimum_permille"],
                fill_maximum_permille=entry["fill_maximum_permille"],
            )
            for entry in catalog["entries"]
        }
        catalogs[version] = LookFamilyCatalog(hashlib.sha256(raw).hexdigest(), families)
    textures = json.loads((root / "assets/textures/manifest.json").read_text(encoding="utf-8"))
    sets = frozenset(str(entry["set_id"]) for entry in textures["sets"])
    return StylePackContext(
        families=catalogs[1].families, texture_sets=sets, family_catalogs=catalogs
    )


def read_piece_budgets(root: Path) -> dict[str, PieceBudget]:
    """The per-family piece budgets, from ``assets/style-packs/piece-budgets.v1.json``.

    Read by the one reader of that file, :func:`exulanica_pieces.budgets.read_budgets`, which the
    generated pieces are made against too, so a pack's pieces and a generated piece are held to
    the same numbers. A file it refuses raises its refusal, a ``ValueError``.
    """
    return dict(read_budgets(root).families)
