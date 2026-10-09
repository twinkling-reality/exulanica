"""The records that make a generated piece a data object: its request, its job and its receipt.

Each is canonical JSON named by its sha256 and read strictly (exact keys, integers only, every
value checked), like every appearance record.

- ``exulanica.generated-asset-request/v2``: what piece is wanted: the look role, the slot and its
  fit, the optional plain description, the pack (id, version, digest, palette, style words), the
  budget with the digest of the piece budgets file it came from, how many variants, and which
  route. Nothing about who asked. A request with a description may carry a person's words, so it
  is cached within its workspace only (:func:`cache_scope`). A piece made to a thing kind names it
  in ``thing_kind`` (key, version and sha256, as the kind catalog states them), so the piece's
  receipt leads back to the kind it was made for. A piece made for a thing a hand holds
  carries ``hold``: the thing kind's grip point and axis and the widest section a hand closes
  around, all in the kind's slot frame, copied from the thing kind and its body plan. A request
  built from a piece recipe catalog entry names it in ``recipe`` (the catalog's version and the
  entry's sha256, :mod:`exulanica_pieces.recipes`), and carries the entry's box fill bar in
  ``box_fill_minimum_permille`` when the entry states one. A ``v1``
  request, whose budget came from a table this module held before the pack format's file existed,
  is still read as it was; only ``v2`` requests are built.
- ``exulanica.generated-asset-job/v2``: one batch, fixed before it runs: the requests, the route's
  weights listing digest, the prompt template's version, every prompt and seed, the code and
  container, and the stop. A ``v1`` job, written before the template had a version, still reads.
- ``exulanica.generated-asset/v1``: one output: the request, job, variant and seed; every input
  and intermediate by digest; every post-process step; the GLB; what was measured against the
  budget and, for a held piece, against its grip; origin generated, truth invented, its licence,
  and the regeneration sentence.

A thing kind's slot frame (whole millimetres, x across the width, y the depth with the front at +y,
z up, the base centre at the origin) meets a piece's glTF frame by the agreed rotation:
X_gltf = -x, Y_gltf = z, Z_gltf = y.

Seeds come from the request digest under a prefix, so a seed is reproducible from the request and
names nothing else.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Final

from exulanica_pieces.budgets import PieceBudget, PieceBudgets
from exulanica_pieces.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_count,
    is_sha256,
    is_text,
    parse_canonical,
    sha256_hex,
)
from exulanica_pieces.vocabulary import (
    FIT,
    GENERATED_FAMILIES,
    budget_for,
    split_role,
)

__all__ = [
    "BOX_FILL_MINIMUM_PER_MILLE",
    "HOLD_AXES",
    "HOLD_FILL_MINIMUM_PER_MILLE",
    "JOB_PROFILE",
    "JOB_PROFILE_V1",
    "POSTPROCESS_VERSION",
    "PROMPT_VERSION",
    "PROMPT_VERSIONS",
    "RECEIPT_PROFILE",
    "REGENERATION",
    "REQUEST_PROFILE",
    "REQUEST_PROFILE_V1",
    "ROUTES",
    "box_fill_minimum",
    "box_fill_permille",
    "build_job",
    "build_receipt",
    "build_request",
    "cache_key",
    "cache_scope",
    "prompt_for",
    "read_job",
    "read_receipt",
    "read_request",
    "seed_for",
]

REQUEST_PROFILE: Final = "exulanica.generated-asset-request/v2"
REQUEST_PROFILE_V1: Final = "exulanica.generated-asset-request/v1"
JOB_PROFILE: Final = "exulanica.generated-asset-job/v2"
JOB_PROFILE_V1: Final = "exulanica.generated-asset-job/v1"
#: The concept prompt's template, :func:`prompt_for`. A change to its words is a new version. A v2
#: template added words from the slot's proportions; measured on Nebius (2026-10-07) it helped no
#: kind and turned the benches end-on, so it was withdrawn, and only the job that measured it names
#: it.
PROMPT_VERSION: Final = "exulanica.generated-asset-prompt/v1"
PROMPT_VERSIONS: Final = frozenset({PROMPT_VERSION, "exulanica.generated-asset-prompt/v2"})
#: The direction a held thing extends from the hand, in the thing kind's slot frame.
HOLD_AXES: Final = ("+x", "-x", "+y", "-y", "+z", "-z")
#: A held piece fills at least this share of its box's longest side, so a grip point measured
#: along that side lands on the piece and not in the gap a smaller fit leaves.
HOLD_FILL_MINIMUM_PER_MILLE: Final = 800
#: A piece made to a thing kind fills at least this share of the kind's box along its longest side,
#: so a gate is not drawn a third of its gateway's size, unless its recipe states another bar.
BOX_FILL_MINIMUM_PER_MILLE: Final = 800
RECEIPT_PROFILE: Final = "exulanica.generated-asset/v1"
REGENERATION: Final = (
    "GPU generation is not bit-exact across hardware, drivers or library versions; the stored "
    "output bytes are the artifact, and a regeneration is a new version, never a replay."
)
#: The deterministic post-process's version. v2 adds the yaw choice of a contained piece; an output
#: is cached under its version, so a piece made by v1 is never served as v2. Here, beside the cache
#: key, so the product reads it without the post-process's numpy half
#: (:mod:`exulanica_pieces.geometry.postprocess` makes pieces under it).
POSTPROCESS_VERSION: Final = "exulanica.generated-asset-postprocess/v2"
#: A: concept picture, TRELLIS-image-large for shape and colour. B: concept picture, Step1X-3D
#: geometry for shape, colour from the picture and the palette. S: the stub of the dry run.
ROUTES: Final = frozenset({"A", "B", "S"})
_SEED_PREFIX: Final = b"exulanica.generated-asset-seed/v1\x00"
_PACK_ID: Final = re.compile(r"[a-z][a-z0-9.-]{0,63}")
_MAX_DESCRIPTION: Final = 80
_MAX_STYLE: Final = 120


def _plain(value: object, limit: int, where: str) -> str:
    """Plain words: trimmed, 1 to ``limit`` characters, no control characters."""
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= limit
        or value != value.strip()
        or any(ord(ch) < 0x20 or 0x7F <= ord(ch) < 0xA0 for ch in value)
    ):
        raise Refused(f"{where} is 1 to {limit} characters of plain words")
    return value


def _mm_box(value: object, where: str) -> dict[str, int]:
    box = exact_keys(value, ("depth", "height", "width"), where)
    for key, item in box.items():
        if not is_count(item, 10) or item > 50_000:
            raise Refused(f"{where}.{key} is 10 to 50,000 mm")
    return box


def _srgb(value: object, where: str) -> list[int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or not all(is_count(channel) and channel <= 255 for channel in value)
    ):
        raise Refused(f"{where} is three bytes of sRGB")
    return value


# --------------------------------------------------------------------------------------------
# Request
# --------------------------------------------------------------------------------------------

_REQUEST_KEYS: Final = (
    "budget",
    "fit",
    "look_role",
    "pack",
    "profile",
    "route",
    "slot_mm",
    "variants",
)
_REQUEST_OPTIONAL: Final = (
    "box_fill_minimum_permille",
    "description",
    "hold",
    "recipe",
    "thing_kind",
    "tile_module_mm",
)
_RECIPE_KEYS: Final = ("catalog_version", "sha256")
_THING_KIND_KEYS: Final = ("key", "sha256", "version")
_THING_KIND_KEY: Final = re.compile(r"[a-z][a-z0-9_]{0,47}")
_HOLD_KEYS: Final = ("axis", "grip", "section_mm_maximum")
_GRIP_KEYS: Final = ("x_mm", "y_mm", "z_mm")
_PACK_KEYS: Final = ("id", "palette", "sha256", "style", "version")
_BUDGET_KEYS: Final = (
    "budgets_sha256",
    "glb_bytes",
    "materials",
    "texture_side_px",
    "triangles",
    "vertices",
)
_BUDGET_KEYS_V1: Final = (
    "glb_bytes",
    "materials",
    "status",
    "texture_side_px",
    "triangles",
    "vertices",
)
#: What a v1 request's budget was checked against, kept so a v1 request reads as it always did. Its
#: kilobytes were read as 1,000 bytes; the pack format's file, which v2 names, reads 1,024.
_V1_STATUS: Final = "provisional: the style pack format's numbers, until that format is approved"
_V1_BUDGETS: Final = MappingProxyType(
    {
        "window": PieceBudget(400, 0, 2, 256, 64_000),
        "door": PieceBudget(1_500, 0, 3, 512, 160_000),
        "fixture": PieceBudget(1_500, 0, 2, 256, 160_000),
        "prop": PieceBudget(1_500, 0, 2, 256, 160_000),
        "plant": PieceBudget(3_000, 0, 2, 512, 300_000),
        "plant.shrub": PieceBudget(800, 0, 2, 512, 300_000),
        "vehicle": PieceBudget(4_000, 0, 3, 512, 400_000),
        "boundary": PieceBudget(0, 200, 2, 256, 64_000),
    }
)


def _check_request(document: object, budgets: PieceBudgets | None) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise Refused("a request is an object")
    keys = set(document)
    if not set(_REQUEST_KEYS) <= keys or not keys <= set(_REQUEST_KEYS) | set(_REQUEST_OPTIONAL):
        raise Refused(
            f"a request has {', '.join(_REQUEST_KEYS)} and optionally "
            f"{', '.join(_REQUEST_OPTIONAL)}"
        )
    if document["profile"] not in (REQUEST_PROFILE, REQUEST_PROFILE_V1):
        raise Refused(f"a request's profile is {REQUEST_PROFILE} or {REQUEST_PROFILE_V1}")
    role = document["look_role"]
    family, _ = split_role(role)
    if family not in GENERATED_FAMILIES:
        raise Refused(f"generation does not make {family} pieces")
    if document["fit"] != FIT[family]:
        raise Refused(f"a {family} piece fits by {FIT[family]}, not {document['fit']!r}")
    slot = _mm_box(document["slot_mm"], "slot_mm")
    if document["fit"] == "tile":
        module = document.get("tile_module_mm")
        if not is_count(module, 100) or module > slot["width"]:
            raise Refused("a tiled piece states its module length, 100 mm to the slot's width")
    elif "tile_module_mm" in document:
        raise Refused("only a tiled piece states a module length")
    if "description" in document:
        _plain(document["description"], _MAX_DESCRIPTION, "description")
    if "hold" in document:
        if document["profile"] == REQUEST_PROFILE_V1:
            raise Refused("a v1 request holds no grip")
        _check_hold(document["hold"], document["fit"], slot)
    if "thing_kind" in document:
        if document["profile"] == REQUEST_PROFILE_V1:
            raise Refused("a v1 request names no thing kind")
        kind = exact_keys(document["thing_kind"], _THING_KIND_KEYS, "thing_kind")
        if (
            not isinstance(kind["key"], str)
            or _THING_KIND_KEY.fullmatch(kind["key"]) is None
            or not is_count(kind["version"], 1)
            or not is_sha256(kind["sha256"])
        ):
            raise Refused("thing_kind names a kind's key, its version from 1 and its sha256")
    if "recipe" in document:
        if document["profile"] == REQUEST_PROFILE_V1:
            raise Refused("a v1 request names no recipe")
        recipe = exact_keys(document["recipe"], _RECIPE_KEYS, "recipe")
        if not is_count(recipe["catalog_version"], 1) or not is_sha256(recipe["sha256"]):
            raise Refused("recipe names the catalog's version from 1 and the entry's sha256")
    if "box_fill_minimum_permille" in document:
        bar = document["box_fill_minimum_permille"]
        if not measures_box_fill(document) or "recipe" not in document:
            raise Refused(
                "only a recipe's piece made to a thing kind, not held, states a box fill bar"
            )
        if not is_count(bar, 1) or bar > 1000:
            raise Refused("box_fill_minimum_permille is 1 to 1,000")
    pack = exact_keys(document["pack"], _PACK_KEYS, "pack")
    if not isinstance(pack["id"], str) or _PACK_ID.fullmatch(pack["id"]) is None:
        raise Refused("pack.id is lower case letters, digits, dots and hyphens")
    if not is_count(pack["version"], 1) or not is_sha256(pack["sha256"]):
        raise Refused("pack names its version from 1 and its sha256")
    _plain(pack["style"], _MAX_STYLE, "pack.style")
    palette = pack["palette"]
    if not isinstance(palette, list) or not 1 <= len(palette) <= 64:
        raise Refused("pack.palette holds 1 to 64 swatches")
    seen = set()
    for index, swatch in enumerate(palette):
        key = tuple(_srgb(swatch, f"pack.palette[{index}]"))
        if key in seen:
            raise Refused("no two palette swatches are alike")
        seen.add(key)
    module = document.get("tile_module_mm")
    if document["profile"] == REQUEST_PROFILE_V1:
        budget = exact_keys(document["budget"], _BUDGET_KEYS_V1, "budget")
        expected = _expected_budget_v1(role, module)
    else:
        budget = exact_keys(document["budget"], _BUDGET_KEYS, "budget")
        if budgets is None:
            raise Refused("a v2 request is read against the piece budgets file it names")
        if budget["budgets_sha256"] != budgets.sha256:
            raise Refused(
                f"budget names piece budgets {budget['budgets_sha256']!r}, "
                f"not the file read ({budgets.sha256})"
            )
        expected = _expected_budget(role, module, budgets)
    if budget != expected:
        raise Refused(f"budget is the pack format's for {role}: {expected}")
    if not is_count(document["variants"], 1) or document["variants"] > 16:
        raise Refused("variants is 1 to 16")
    if document["route"] not in ROUTES:
        raise Refused(f"route is one of {', '.join(sorted(ROUTES))}")
    return document


def _check_hold(value: object, fit: str, slot: Mapping[str, int]) -> None:
    hold = exact_keys(value, _HOLD_KEYS, "hold")
    if fit != "contain":
        raise Refused("only a piece fitted by contain is made for a hand")
    if hold["axis"] not in HOLD_AXES:
        raise Refused(f"hold.axis is one of {', '.join(HOLD_AXES)}")
    maximum = hold["section_mm_maximum"]
    if not is_count(maximum, 1) or maximum > 1000:
        raise Refused("hold.section_mm_maximum is 1 to 1,000 mm, the body plan's figure")
    grip = exact_keys(hold["grip"], _GRIP_KEYS, "hold.grip")
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in grip.values()):
        raise Refused("hold.grip is whole millimetres")
    if (
        2 * abs(grip["x_mm"]) > slot["width"]
        or 2 * abs(grip["y_mm"]) > slot["depth"]
        or not 0 <= grip["z_mm"] <= slot["height"]
    ):
        raise Refused("hold.grip lies inside the slot: x across the width, y the depth, z up")


def _expected_budget(role: str, module_mm: object, budgets: PieceBudgets) -> dict[str, Any]:
    budget = budget_for(role, budgets.families)
    triangles = budget.triangles
    if budget.triangles_per_metre:
        if not is_count(module_mm, 100):
            raise Refused("a tiled piece states its module length, 100 mm to the slot's width")
        triangles = budget.triangle_limit(module_mm)  # type: ignore[arg-type]
        if triangles < 1:
            raise Refused(f"a {role} module of {module_mm} mm is allowed no triangle")
    return {
        "budgets_sha256": budgets.sha256,
        "glb_bytes": budget.glb_bytes,
        "materials": budget.materials,
        "texture_side_px": budget.texture_side_px,
        "triangles": triangles,
        "vertices": budgets.vertices_per_triangle * triangles,
    }


def _expected_budget_v1(role: str, module_mm: object) -> dict[str, Any]:
    budget = budget_for(role, _V1_BUDGETS)
    triangles = budget.triangles
    if budget.triangles_per_metre:
        if not is_count(module_mm, 100):
            raise Refused("a tiled piece states its module length, 100 mm to the slot's width")
        triangles = max(1, budget.triangles_per_metre * module_mm // 1000)  # type: ignore[operator]
    return {
        "glb_bytes": budget.glb_bytes,
        "materials": budget.materials,
        "status": _V1_STATUS,
        "texture_side_px": budget.texture_side_px,
        "triangles": triangles,
        "vertices": 3 * triangles,
    }


def build_request(
    *,
    look_role: str,
    slot_mm: Mapping[str, int],
    pack: Mapping[str, Any],
    variants: int,
    route: str,
    budgets: PieceBudgets,
    description: str | None = None,
    tile_module_mm: int | None = None,
    hold: Mapping[str, Any] | None = None,
    thing_kind: Mapping[str, Any] | None = None,
    recipe: Mapping[str, Any] | None = None,
    box_fill_minimum_permille: int | None = None,
) -> bytes:
    """A v2 request's canonical bytes; its budget is filled from the pack format's file."""
    family, _ = split_role(look_role)
    budget_for(look_role, budgets.families)  # refuses a family generation does not make
    document: dict[str, Any] = {
        "budget": _expected_budget(look_role, tile_module_mm, budgets),
        "fit": FIT[family],
        "look_role": look_role,
        "pack": dict(pack),
        "profile": REQUEST_PROFILE,
        "route": route,
        "slot_mm": dict(slot_mm),
        "variants": variants,
    }
    if description is not None:
        document["description"] = description
    if tile_module_mm is not None:
        document["tile_module_mm"] = tile_module_mm
    if hold is not None:
        document["hold"] = {**hold, "grip": dict(hold["grip"])}
    if thing_kind is not None:
        document["thing_kind"] = dict(thing_kind)
    if recipe is not None:
        document["recipe"] = dict(recipe)
    if box_fill_minimum_permille is not None:
        document["box_fill_minimum_permille"] = box_fill_minimum_permille
    raw = canonical_bytes(document)
    read_request(raw, budgets)
    return raw


def read_request(raw: bytes, budgets: PieceBudgets | None) -> dict[str, Any]:
    """A request, strictly. A v2 request is checked against ``budgets``, the file it names; a v1
    request against the table it was made with, so ``budgets`` may be None for it."""
    return _check_request(parse_canonical(raw, "request"), budgets)


def cache_scope(request: Mapping[str, Any], recipe_words: str | None = None) -> str:
    """``catalog`` when the request is built from catalog content only, else ``workspace``.

    A description may carry a person's words, and a shared cache would tell one workspace what
    another asked for, so such a request is cached within its own workspace. A description is
    catalog content only when it is ``recipe_words``: the words of the recipe catalog entry the
    request names, which the caller looked up by that entry's digest
    (:meth:`exulanica_pieces.recipes.PieceRecipes.words_of`).
    """
    if "description" not in request:
        return "catalog"
    if "recipe" in request and recipe_words is not None and request["description"] == recipe_words:
        return "catalog"
    return "workspace"


def cache_key(request_sha256: str, components_sha256: str, postprocess_version: str) -> str:
    """What an output is cached under: the same key is never generated twice."""
    for value in (request_sha256, components_sha256):
        if not is_sha256(value):
            raise Refused("a cache key is made of sha256 digests")
    return sha256_hex(
        canonical_bytes(
            {
                "components_sha256": components_sha256,
                "postprocess": postprocess_version,
                "request_sha256": request_sha256,
            }
        )
    )


def seed_for(request_sha256: str, variant: int) -> int:
    """A 63-bit seed from the request digest under a prefix, one per variant."""
    if not is_sha256(request_sha256) or not is_count(variant):
        raise Refused("a seed is drawn from a request digest and a variant number")
    digest = hashlib.sha256(
        _SEED_PREFIX + bytes.fromhex(request_sha256) + variant.to_bytes(4, "big")
    )
    return int.from_bytes(digest.digest()[:8], "big") >> 1


#: How a held thing stands in its picture, by the direction it extends from the hand.
_HELD_POSE: Final = MappingProxyType(
    {
        "+z": "standing upright, its handle at the bottom",
        "-z": "hanging from a ring or handle at its top",
        "+x": "lying on its side, its handle at one end",
        "-x": "lying on its side, its handle at one end",
        "+y": "lying on its side, its handle at the back",
        "-y": "lying on its side, its handle at the front",
    }
)


def prompt_for(request: Mapping[str, Any]) -> str:
    """The concept picture's prompt, from the request alone, by the template :data:`PROMPT_VERSION`
    names. A held thing's picture shows it posed as its grip says, so the model draws the handle
    where the hand will be."""
    _, leaf = split_role(request["look_role"])
    subject = request.get("description") or leaf.replace("_", " ")
    slot = request["slot_mm"]
    pose = f"{_HELD_POSE[request['hold']['axis']]}, " if "hold" in request else ""
    return (
        f"{subject}, a single {request['look_role'].split('.')[0]} for a game world, "
        f"{request['pack']['style']}, about {slot['width']} mm wide, {slot['height']} mm tall and "
        f"{slot['depth']} mm deep, {pose}whole object in frame, three-quarter front view, "
        "plain light grey background, no text, no lettering, no logo"
    )


# --------------------------------------------------------------------------------------------
# Job
# --------------------------------------------------------------------------------------------

_JOB_KEYS: Final = (
    "code_sha256",
    "components_sha256",
    "container",
    "items",
    "profile",
    "prompt_version",
    "route",
    "stop",
)
_JOB_KEYS_V1: Final = tuple(key for key in _JOB_KEYS if key != "prompt_version")
_ITEM_KEYS: Final = ("prompt", "request_sha256", "seed", "variant")
#: An item may instead start from a cut-out another job made, named by its sha256, so two routes
#: are compared on the same pictures.
_ITEM_OPTIONAL: Final = ("cutout_sha256",)


def build_job(
    *,
    route: str,
    components_sha256: str,
    requests: Sequence[bytes],
    code_sha256: str,
    container: str,
    estimate_seconds: int,
    budgets: PieceBudgets | None,
    cutouts: Mapping[tuple[str, int], str] | None = None,
) -> bytes:
    """One batch: every variant of every request, its prompt and seed, fixed before it runs.

    ``cutouts`` maps (request sha256, variant) to the cut-out an item starts from instead of a
    concept picture of its own."""
    items = []
    for raw in requests:
        request = read_request(raw, budgets)
        if request["route"] != route:
            raise Refused("every request in a job takes the job's route")
        digest = sha256_hex(raw)
        for variant in range(request["variants"]):
            item = {
                "prompt": prompt_for(request),
                "request_sha256": digest,
                "seed": seed_for(digest, variant),
                "variant": variant,
            }
            if cutouts and (digest, variant) in cutouts:
                item["cutout_sha256"] = cutouts[(digest, variant)]
            items.append(item)
    document = {
        "code_sha256": code_sha256,
        "components_sha256": components_sha256,
        "container": container,
        "items": items,
        "profile": JOB_PROFILE,
        "prompt_version": PROMPT_VERSION,
        "route": route,
        "stop": {
            "estimate_seconds": estimate_seconds,
            "stop_at_seconds": estimate_seconds * 3 // 2,
        },
    }
    raw = canonical_bytes(document)
    read_job(raw)
    return raw


def read_job(raw: bytes) -> dict[str, Any]:
    document = parse_canonical(raw, "job")
    v1 = isinstance(document, dict) and document.get("profile") == JOB_PROFILE_V1
    document = exact_keys(document, _JOB_KEYS_V1 if v1 else _JOB_KEYS, "job")
    if not v1 and (
        document["profile"] != JOB_PROFILE or document["prompt_version"] not in PROMPT_VERSIONS
    ):
        raise Refused(
            f"a job's profile is {JOB_PROFILE} or {JOB_PROFILE_V1}, and a {JOB_PROFILE} job's "
            f"prompt template is one of {sorted(PROMPT_VERSIONS)}"
        )
    if document["route"] not in ROUTES:
        raise Refused(f"a job's route is one of {sorted(ROUTES)}")
    for key in ("code_sha256", "components_sha256"):
        if not is_sha256(document[key]):
            raise Refused(f"job.{key} is a sha256")
    container = document["container"]
    if not (
        container == "stub"
        or (
            isinstance(container, str)
            and container.startswith("sha256:")
            and is_sha256(container[7:])
        )
    ):
        raise Refused("job.container is an image digest, or stub for the dry run")
    if (container == "stub") != (document["route"] == "S"):
        raise Refused("only the stub route runs without a container, and it runs only without one")
    stop = exact_keys(document["stop"], ("estimate_seconds", "stop_at_seconds"), "job.stop")
    if (
        not is_count(stop["estimate_seconds"], 1)
        or stop["stop_at_seconds"] != stop["estimate_seconds"] * 3 // 2
    ):
        raise Refused("job.stop is an estimate and its 150 per cent")
    items = document["items"]
    if not isinstance(items, list) or not items:
        raise Refused("a job has at least one item")
    seen = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not set(_ITEM_KEYS) <= set(item) <= set(
            _ITEM_KEYS + _ITEM_OPTIONAL
        ):
            raise Refused(
                f"job.items[{index}] has {', '.join(_ITEM_KEYS)} and optionally a cut-out"
            )
        if "cutout_sha256" in item and not is_sha256(item["cutout_sha256"]):
            raise Refused(f"job.items[{index}].cutout_sha256 is a sha256")
        if not is_sha256(item["request_sha256"]) or not is_count(item["variant"]):
            raise Refused(f"job.items[{index}] names a request and a variant")
        if item["seed"] != seed_for(item["request_sha256"], item["variant"]):
            raise Refused(f"job.items[{index}].seed is not the request's seed for that variant")
        if not is_text(item["prompt"]):
            raise Refused(f"job.items[{index}].prompt is printable text")
        key = (item["request_sha256"], item["variant"])
        if key in seen:
            raise Refused(f"job.items[{index}] repeats a request and variant")
        seen.add(key)
    return document


# --------------------------------------------------------------------------------------------
# Receipt
# --------------------------------------------------------------------------------------------

_RECEIPT_KEYS: Final = (
    "components_sha256",
    "inputs",
    "job_sha256",
    "licence",
    "measured",
    "origin",
    "output",
    "postprocess",
    "profile",
    "regeneration",
    "request_sha256",
    "runtime",
    "seconds",
    "seed",
    "truth",
    "variant",
    "verdict",
)
_MEASURED_KEYS: Final = (
    "glb_bytes",
    "materials",
    "size_mm",
    "texture_side_px",
    "triangles",
    "vertices",
)
_HOLD_MEASURED_KEYS: Final = ("band_mm", "fill_permille", "grip_in_section", "section_mm")
_SECONDS_KEYS: Final = ("concept", "cutout", "mesh", "postprocess")
_STEPS: Final = ("orient", "simplify", "fit", "palette", "write")


def box_fill_permille(size_mm: Mapping[str, int], slot_mm: Mapping[str, int]) -> int:
    """The fitted size along the slot's longest side, per mille of that side."""
    longest = max(("width", "height", "depth"), key=lambda key: (slot_mm[key], key))
    return size_mm[longest] * 1000 // slot_mm[longest]


def box_fill_minimum(request: Mapping[str, Any]) -> int:
    """The box fill bar a piece made to ``request`` is held to: its recipe's, else the default."""
    return int(request.get("box_fill_minimum_permille", BOX_FILL_MINIMUM_PER_MILLE))


def measures_box_fill(request: Mapping[str, Any]) -> bool:
    """A piece made to a thing kind and not held is held to its box's fill.

    A held piece already is, by its hold fill."""
    return "thing_kind" in request and "hold" not in request


def verdict(
    measured: Mapping[str, Any],
    budget: Mapping[str, Any],
    hold: Mapping[str, Any] | None = None,
    box_fill_bar: int = BOX_FILL_MINIMUM_PER_MILLE,
) -> dict[str, Any]:
    """Within budget, or each measure over it named. The budget is the request's.

    A piece whose box fill was measured names ``box_fill`` when it fills less than
    ``box_fill_bar`` per mille, the request's :func:`box_fill_minimum`.

    A held piece also names ``hold_fill`` when it fills less than
    :data:`HOLD_FILL_MINIMUM_PER_MILLE` of its box's longest side, and ``grip_section`` when
    nothing crosses the grip, the section through it is wider than the hand closes around, or the
    grip point lies outside that section."""
    over = [
        key
        for key in ("glb_bytes", "materials", "texture_side_px", "triangles", "vertices")
        if measured[key] > budget[key]
    ]
    if "box_fill_permille" in measured and measured["box_fill_permille"] < box_fill_bar:
        over.append("box_fill")
    if hold is not None:
        held = measured["hold"]
        if held["fill_permille"] < HOLD_FILL_MINIMUM_PER_MILLE:
            over.append("hold_fill")
        section = held["section_mm"]
        if (
            section is None
            or max(section.values()) > hold["section_mm_maximum"]
            or not held["grip_in_section"]
        ):
            over.append("grip_section")
    return {"over": sorted(over), "within": not over}


def build_receipt(document: Mapping[str, Any], request: Mapping[str, Any]) -> bytes:
    raw = canonical_bytes(dict(document))
    read_receipt(raw, request)
    return raw


def read_receipt(raw: bytes, request: Mapping[str, Any]) -> dict[str, Any]:
    """A receipt, checked against the request it names (its budget and seed)."""
    document = exact_keys(parse_canonical(raw, "receipt"), _RECEIPT_KEYS, "receipt")
    if document["profile"] != RECEIPT_PROFILE:
        raise Refused(f"a receipt's profile is {RECEIPT_PROFILE}")
    if document["origin"] != "generated" or document["truth"] != "invented":
        raise Refused("a generated piece is origin generated and truth invented")
    if document["licence"] != "CC0-1.0":
        raise Refused("a generated piece is published CC0-1.0")
    if document["regeneration"] != REGENERATION:
        raise Refused("a receipt carries the regeneration sentence verbatim")
    request_sha256 = sha256_hex(canonical_bytes(dict(request)))
    if document["request_sha256"] != request_sha256:
        raise Refused("the receipt names another request")
    if document["seed"] != seed_for(request_sha256, document["variant"]):
        raise Refused("the receipt's seed is not the request's seed for its variant")
    if document["variant"] >= request["variants"]:
        raise Refused("the receipt's variant is past the request's count")
    for key in ("components_sha256", "job_sha256"):
        if not is_sha256(document[key]):
            raise Refused(f"receipt.{key} is a sha256")
    inputs = document["inputs"]
    if (
        not isinstance(inputs, dict)
        or not inputs
        or not all(is_sha256(value) for value in inputs.values())
    ):
        raise Refused("receipt.inputs names each input and intermediate by sha256")
    steps = (
        document["postprocess"].get("steps") if isinstance(document["postprocess"], dict) else None
    )
    if not isinstance(steps, list) or [step.get("step") for step in steps] != list(_STEPS):
        raise Refused(f"receipt.postprocess.steps are {', '.join(_STEPS)} in that order")
    output = exact_keys(document["output"], ("bytes", "sha256"), "receipt.output")
    if not is_sha256(output["sha256"]) or not is_count(output["bytes"], 1):
        raise Refused("receipt.output names the GLB by sha256 and size")
    hold = request.get("hold")
    measured = exact_keys(
        document["measured"],
        _MEASURED_KEYS
        + (("hold",) if hold is not None else ())
        + (("box_fill_permille",) if measures_box_fill(request) else ()),
        "receipt.measured",
    )
    if measures_box_fill(request) and (
        measured["box_fill_permille"] != box_fill_permille(measured["size_mm"], request["slot_mm"])
    ):
        raise Refused(
            "receipt.measured.box_fill_permille is the size along the slot's longest side"
        )
    _mm_box(measured["size_mm"], "receipt.measured.size_mm")
    if measured["glb_bytes"] != output["bytes"]:
        raise Refused("the measured size is the output's size")
    if hold is not None:
        _check_hold_measured(measured["hold"], hold["axis"])
    if document["verdict"] != verdict(measured, request["budget"], hold, box_fill_minimum(request)):
        raise Refused("receipt.verdict is not what the measures and the request's budget say")
    exact_keys(document["seconds"], _SECONDS_KEYS, "receipt.seconds")
    if not all(is_count(value) for value in document["seconds"].values()):
        raise Refused("receipt.seconds are whole seconds")
    if not isinstance(document["runtime"], dict):
        raise Refused("receipt.runtime states the machine and libraries")
    return document


def _check_hold_measured(value: object, axis: str) -> None:
    held = exact_keys(value, _HOLD_MEASURED_KEYS, "receipt.measured.hold")
    if not is_count(held["band_mm"], 1) or not is_count(held["fill_permille"]):
        raise Refused("receipt.measured.hold states its band and fill in whole numbers")
    if not isinstance(held["grip_in_section"], bool):
        raise Refused("receipt.measured.hold.grip_in_section is true or false")
    section = held["section_mm"]
    across = tuple(f"{a}_mm" for a in "xyz" if a != axis[1])
    if section is not None and (
        not isinstance(section, dict)
        or set(section) != set(across)
        or not all(is_count(v) for v in section.values())
    ):
        raise Refused(f"receipt.measured.hold.section_mm is null or whole mm along {across}")
    if section is None and held["grip_in_section"]:
        raise Refused("a grip cannot lie in a section that is not there")
