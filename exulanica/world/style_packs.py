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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from exulanica_pieces.budgets import BUDGETS_PROFILE, PieceBudget, read_budgets

__all__ = [
    "BUDGETS_PROFILE",
    "COLOUR_ENCODING",
    "EXTENSION_MEDIA_TYPES",
    "IMAGE_MEDIA_TYPES",
    "PREVIEW_MAX_BYTES",
    "PROFILE",
    "LookFamily",
    "PieceBudget",
    "StylePackContext",
    "StylePackRefused",
    "canonical_json",
    "load_context",
    "manifest_sha256",
    "read_manifest",
    "read_piece_budgets",
    "split_look_role",
]

PROFILE: Final = "exulanica.style-pack/v1"
COLOUR_ENCODING: Final = "exulanica.srgb8-linear16/v1"
LICENCES: Final = ("CC0-1.0", "CC-BY-4.0")
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
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")
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
class StylePackContext:
    families: Mapping[str, LookFamily]
    texture_sets: frozenset[str]


Reader = Callable[[Any, str], Any]


def _fail(reason: str, path: str, detail: str) -> Any:
    raise StylePackRefused(reason, path, detail)


def _join(path: str, key: str) -> str:
    return key if path == "" else f"{path}.{key}"


def _object(value: Any, path: str, fields: Mapping[str, Reader]) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("shape", path, "must be an object")
    for key in value:
        if key not in fields:
            _fail("shape", path, f"has an unknown key {json.dumps(key)}")
    out: dict[str, Any] = {}
    for key, read in fields.items():
        if key not in value:
            _fail("shape", path, f"is missing {json.dumps(key)}")
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
        # JavaScript counts UTF-16 code units; count the same here.
        if len(value.encode("utf-16-le")) // 2 > maximum:
            _fail("range", path, f"must be at most {maximum} characters")
        if _CONTROL.search(value):
            _fail("shape", path, "must hold no control characters")
        return str(value)

    return read


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


def read_manifest(value: Any, context: StylePackContext) -> dict[str, Any]:
    """Read a manifest, or refuse it with the first rule it breaks, by reason and path."""

    def look_role_key(dressings: tuple[str, ...]) -> Callable[[str, str], None]:
        def read(key: str, path: str) -> None:
            family, _leaf = split_look_role(key, path)
            known = context.families.get(family)
            if known is None:
                _fail("reference", path, f"names no look family {json.dumps(family)}")
            elif known.dressing not in dressings:
                _fail("reference", path, f"family {json.dumps(family)} is not dressed this way")

        return read

    def preset_key(key: str, path: str) -> None:
        if _KEY.fullmatch(key) is None:
            _fail("shape", path, "must be a preset key")

    def surface(value: Any, path: str) -> dict[str, Any]:
        key = _pattern(_KEY, "a swatch key")
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
            "preview": _nullable(
                _pattern(_IMAGE_PATH, "a lowercase relative path ending .jpg, .png or .webp")
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
            "surfaces": _record(look_role_key(("surface", "both")), surface, 256),
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
    _check_whole(manifest, context)
    return manifest


def _check_whole(manifest: dict[str, Any], context: StylePackContext) -> None:
    if manifest["provenance"]["kind"] != manifest["origin"]:
        _fail("reference", "provenance.kind", "must equal the origin")
    licence = manifest["licence"]
    if licence["id"] == "CC-BY-4.0" and licence["attribution"] is None:
        _fail("licence", "licence.attribution", "is required for CC-BY-4.0")
    if licence["id"] == "CC0-1.0" and licence["attribution"] is not None:
        _fail("licence", "licence.attribution", "must be null for CC0-1.0")
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
        if file["media_type"] in IMAGE_MEDIA_TYPES and file["bytes"] > PREVIEW_MAX_BYTES:
            _fail(
                "range", f"files[{index}].bytes", f"a picture is at most {PREVIEW_MAX_BYTES} bytes"
            )
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
    preview = manifest["preview"]
    if preview is not None:
        if preview not in listed:
            _fail("reference", "preview", f"names no listed file {json.dumps(preview)}")
        used.add(preview)
    for path in listed:
        if path not in used:
            _fail("reference", "files", f"lists {json.dumps(path)}, which nothing uses")


def _utf16_key(text: str) -> bytes:
    """JavaScript compares strings by UTF-16 code units; so does this."""
    return text.encode("utf-16-be")


def canonical_json(value: Any) -> str:
    """Canonical JSON: keys sorted, no whitespace, ASCII with lowercase escapes, integers only."""
    if isinstance(value, float):
        raise StylePackRefused("shape", "", "a canonical manifest holds whole numbers only")
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """The manifest's identity: the SHA-256 of its canonical bytes."""
    return hashlib.sha256(canonical_json(manifest).encode("ascii")).hexdigest()


def load_context(root: Path) -> StylePackContext:
    """The world kinds' look families and the texture manifest's set ids, read from ``root``."""
    catalog = json.loads(
        (root / "assets/catalogs/world-kinds/look-family.v1.json").read_text(encoding="utf-8")
    )
    families = {
        entry["key"]: LookFamily(
            fit=entry["fit"],
            dressing=entry["dressing"],
            fill_minimum_permille=entry["fill_minimum_permille"],
            fill_maximum_permille=entry["fill_maximum_permille"],
        )
        for entry in catalog["entries"]
    }
    textures = json.loads((root / "assets/textures/manifest.json").read_text(encoding="utf-8"))
    sets = frozenset(str(entry["set_id"]) for entry in textures["sets"])
    return StylePackContext(families=families, texture_sets=sets)


def read_piece_budgets(root: Path) -> dict[str, PieceBudget]:
    """The per-family piece budgets, from ``assets/style-packs/piece-budgets.v1.json``.

    Read by the one reader of that file, :func:`exulanica_pieces.budgets.read_budgets`, which the
    generated pieces are made against too, so a pack's pieces and a generated piece are held to
    the same numbers. A file it refuses raises its refusal, a ``ValueError``.
    """
    return dict(read_budgets(root).families)
