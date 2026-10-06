"""The records that make a generated piece a data object: its request, its job and its receipt.

Each is canonical JSON named by its sha256 and read strictly (exact keys, integers only, every
value checked), like every appearance record.

- ``exulanica.generated-asset-request/v2``: what piece is wanted: the look role, the slot and its
  fit, the optional plain description, the pack (id, version, digest, palette, style words), the
  budget with the digest of the piece budgets file it came from, how many variants, and which
  route. Nothing about who asked. A request with a description may carry a person's words, so it
  is cached within its workspace only (:func:`cache_scope`). A ``v1`` request, whose budget came
  from a table this module held before the pack format's file existed, is still read as it was;
  only ``v2`` requests are built.
- ``exulanica.generated-asset-job/v1``: one batch, fixed before it runs: the requests, the route's
  weights listing digest, every prompt and seed, the code and container, and the stop.
- ``exulanica.generated-asset/v1``: one output: the request, job, variant and seed; every input
  and intermediate by digest; every post-process step; the GLB; what was measured against the
  budget; origin generated, truth invented, its licence, and the regeneration sentence.

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
    "JOB_PROFILE",
    "RECEIPT_PROFILE",
    "REGENERATION",
    "REQUEST_PROFILE",
    "REQUEST_PROFILE_V1",
    "ROUTES",
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
JOB_PROFILE: Final = "exulanica.generated-asset-job/v1"
RECEIPT_PROFILE: Final = "exulanica.generated-asset/v1"
REGENERATION: Final = (
    "GPU generation is not bit-exact across hardware, drivers or library versions; the stored "
    "output bytes are the artifact, and a regeneration is a new version, never a replay."
)
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
_REQUEST_OPTIONAL: Final = ("description", "tile_module_mm")
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
    raw = canonical_bytes(document)
    read_request(raw, budgets)
    return raw


def read_request(raw: bytes, budgets: PieceBudgets | None) -> dict[str, Any]:
    """A request, strictly. A v2 request is checked against ``budgets``, the file it names; a v1
    request against the table it was made with, so ``budgets`` may be None for it."""
    return _check_request(parse_canonical(raw, "request"), budgets)


def cache_scope(request: Mapping[str, Any]) -> str:
    """``catalog`` when the request is built from catalog content only, else ``workspace``.

    A description may carry a person's words, and a shared cache would tell one workspace what
    another asked for, so such a request is cached within its own workspace.
    """
    return "workspace" if "description" in request else "catalog"


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


def prompt_for(request: Mapping[str, Any]) -> str:
    """The concept picture's prompt, from the request alone, by a fixed template."""
    _, leaf = split_role(request["look_role"])
    subject = request.get("description") or leaf.replace("_", " ")
    slot = request["slot_mm"]
    return (
        f"{subject}, a single {request['look_role'].split('.')[0]} for a game world, "
        f"{request['pack']['style']}, about {slot['width']} mm wide, {slot['height']} mm tall and "
        f"{slot['depth']} mm deep, whole object in frame, three-quarter front view, plain light "
        "grey background, no text, no lettering, no logo"
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
    "route",
    "stop",
)
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
    document = exact_keys(parse_canonical(raw, "job"), _JOB_KEYS, "job")
    if document["profile"] != JOB_PROFILE or document["route"] not in ROUTES:
        raise Refused(f"a job's profile is {JOB_PROFILE} and its route one of {sorted(ROUTES)}")
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
_SECONDS_KEYS: Final = ("concept", "cutout", "mesh", "postprocess")
_STEPS: Final = ("orient", "simplify", "fit", "palette", "write")


def verdict(measured: Mapping[str, Any], budget: Mapping[str, Any]) -> dict[str, Any]:
    """Within budget, or each measure over it named. The budget is the request's."""
    over = sorted(
        key
        for key in ("glb_bytes", "materials", "texture_side_px", "triangles", "vertices")
        if measured[key] > budget[key]
    )
    return {"over": over, "within": not over}


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
    measured = exact_keys(document["measured"], _MEASURED_KEYS, "receipt.measured")
    _mm_box(measured["size_mm"], "receipt.measured.size_mm")
    if measured["glb_bytes"] != output["bytes"]:
        raise Refused("the measured size is the output's size")
    if document["verdict"] != verdict(measured, request["budget"]):
        raise Refused("receipt.verdict is not what the measures and the request's budget say")
    exact_keys(document["seconds"], _SECONDS_KEYS, "receipt.seconds")
    if not all(is_count(value) for value in document["seconds"].values()):
        raise Refused("receipt.seconds are whole seconds")
    if not isinstance(document["runtime"], dict):
        raise Refused("receipt.runtime states the machine and libraries")
    return document
