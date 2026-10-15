"""A workspace's static glTF binary: what may be admitted, and how it is prepared for placement.

This is the one content profile a person may admit to their own workspace today
(:mod:`exulanica.world.workspace_assets`): a self-contained glTF 2.0 binary with one scene of
triangles, embedded PNG or JPEG textures, and nothing that moves, deforms or reaches outside the
file. It is not the operator's importer (:mod:`exulanica.world.asset_import`), whose container
check it reuses unchanged as a second wall, and it never makes a global catalog row.

Every step says what kind of step it is, and the preparation receipt repeats the word:

- **validate** decides and changes nothing. :func:`inspect_static_glb` is the whole admission
  check. It reads the JSON chunk and the image headers only, so an upload route can run it before
  a row or a byte is written, and every limit is checked before the loop it bounds.
- **measure** reads facts from the content (exact bounds from the vertex data, counts, decoded
  image sizes) and changes nothing.
- **transform** changes bytes. Exactly one step does: :func:`prepare_static_glb` rewrites the JSON
  chunk so the object stands on its origin in metres (one new root node carrying the declared
  unit's scale and the translation that puts the bottom centre of its bounds at the origin), the
  position bounds are exact, and no ``extras`` survive. The binary chunk is copied byte for byte.

**The bounds are declared, not measured capacity.** The byte and JSON ceilings are the browser's
container boundary (``validate_import_container`` states the same ones). The counts bound the work
this module and a renderer do; instancing is counted, so one mesh drawn by a thousand nodes costs
a thousand draws here as it would there. Renderer frame cost at these bounds is not measured by
anything in this module.

**No I/O.** No database, store or network. Decoding a texture is the caller's
(``decode_image``), because the one place pixels are decoded is :mod:`exulanica.corpus.decode`
and a validator that imported a decoder would be a second one.

**Deterministic.** The output is a pure function of the input bytes, the declared unit and this
module's version: sorted keys, no whitespace, IEEE-754 doubles written by Python's shortest
round-trip representation, and the binary chunk untouched. A change that can move an output byte
is a new :data:`PREPARER_VERSION`, and tests hold golden digests to that rule.

The profile's words, bounds and shapes are :mod:`exulanica.world.static_glb_format`'s, and the
admission's per-part checks :mod:`exulanica.world.static_glb_checks`'s.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import struct
import sys
from array import array
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from types import MappingProxyType
from typing import Any

from exulanica.canonical import ceil_div, round_half_down
from exulanica.world.asset_import import validate_import_container
from exulanica.world.static_glb_checks import (
    _IDENTITY,
    _axis_aligned,
    _check_accessors,
    _check_asset,
    _check_buffers,
    _check_graph,
    _check_images,
    _check_materials,
    _check_meshes,
    _check_nodes,
    _chunks,
    _declared_extensions,
    _document,
    _instances,
    _multiply,
    _point,
    _refuse,
    _roots,
)
from exulanica.world.static_glb_format import (
    _CENTRE_TOLERANCE_M,
    _CHUNK_BIN,
    _CHUNK_JSON,
    _COMPONENTS,
    _FLOAT,
    _GLTF_MAGIC,
    _TOP_LEVEL,
    _WIDTHS,
    CONTENT_REASONS,
    GENERATOR,
    LIMITS,
    MAX_JSON_BYTES,
    MEDIA_TYPE,
    PLACEABLE_OBJECT_PROFILE,
    PREPARER_ID,
    PREPARER_VERSION,
    PROFILE,
    UNITS,
    Compatibility,
    InspectedGlb,
    PreparedGlb,
    StaticGlbLimits,
    StaticGlbRefused,
    _Accessor,
    _Primitive,
)

__all__ = [
    "CONTENT_REASONS",
    "GENERATOR",
    "LIMITS",
    "MAX_JSON_BYTES",
    "MEDIA_TYPE",
    "PLACEABLE_OBJECT_PROFILE",
    "PREPARER_ID",
    "PREPARER_VERSION",
    "PROFILE",
    "UNITS",
    "Compatibility",
    "InspectedGlb",
    "PreparedGlb",
    "StaticGlbLimits",
    "StaticGlbRefused",
    "StaticMeshCoverage",
    "StaticMeshInstanceBounds",
    "inspect_static_glb",
    "prepare_static_glb",
    "static_mesh_instance_bounds",
]


# -- admission -----------------------------------------------------------------------------------


def inspect_static_glb(payload: bytes, limits: StaticGlbLimits = LIMITS) -> InspectedGlb:
    """Every admission check, reading the JSON chunk and image headers only. Changes nothing.

    Raises :class:`StaticGlbRefused` with the first reason found. The order is fixed so one
    container always answers the same reason: the container, then what it declares it needs
    (extensions and references), then the operator importer's container check as a second wall,
    then the static profile, then the bounds.
    """
    json_chunk, bin_chunk = _chunks(payload)
    document = _document(json_chunk)
    _declared_extensions(document)
    try:
        validate_import_container(payload)
    except ValueError as error:
        raise _refuse("malformed_container", str(error)) from None
    unknown = sorted(set(document) - _TOP_LEVEL)
    if unknown:
        raise _refuse("unsupported_feature", f"the container states {', '.join(unknown)}")
    for name in ("animations", "skins"):
        if document.get(name):
            raise _refuse("not_static", f"the container holds {name}")
    if document.get("cameras"):
        raise _refuse("unsupported_feature", "the container holds cameras")
    _check_asset(document)
    views, _ = _check_buffers(document, bin_chunk, limits)
    accessors = _check_accessors(document, views, limits)
    images = _check_images(document, views, bin_chunk, limits)
    textures, materials = _check_materials(document, len(images), limits)
    meshes = _check_meshes(document, accessors, materials, limits)
    nodes = _check_nodes(document, len(meshes), limits)
    roots = _roots(document, nodes)
    _check_graph(nodes, roots, limits)
    instances, drawn = _instances(nodes, roots, meshes, limits)
    counts = {
        "nodes": len(nodes),
        "meshes": len(meshes),
        "primitives": sum(len(mesh) for mesh in meshes),
        "accessors": len(accessors),
        "images": len(images),
        "textures": textures,
        "materials": materials,
        "texels": sum(image.width_px * image.height_px for image in images),
        **drawn,
    }
    return InspectedGlb(
        document=document,
        json_chunk=json_chunk,
        bin_chunk=bin_chunk or b"",
        images=images,
        instances=instances,
        roots=roots,
        counts=MappingProxyType(counts),
        accessors=tuple(accessors),
        meshes=tuple(tuple(mesh) for mesh in meshes),
    )


# -- preparation ---------------------------------------------------------------------------------


def _values(bin_chunk: bytes, accessor: _Accessor) -> array[Any]:
    """Every component of an accessor, in order, as one typed array."""
    code, _ = _COMPONENTS[accessor.component]
    width = _WIDTHS[accessor.kind]
    if accessor.stride == accessor.element:
        end = accessor.offset + accessor.element * accessor.count
        values = array(code, bin_chunk[accessor.offset : end])
    else:
        values = array(code)
        for number in range(accessor.count):
            start = accessor.offset + number * accessor.stride
            values.frombytes(bin_chunk[start : start + accessor.element])
    if len(values) != width * accessor.count:
        raise _refuse("malformed_container", f"accessors[{accessor.index}] is cut short")
    if sys.byteorder == "big":
        values.byteswap()
    return values


def _position_box(
    values: array[Any], index: int
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    lows = [math.inf, math.inf, math.inf]
    highs = [-math.inf, -math.inf, -math.inf]
    for axis in range(3):
        column = values[axis::3]
        for value in column:
            if not math.isfinite(value):
                raise _refuse("invalid_geometry", f"accessors[{index}] holds a non-finite position")
        lows[axis] = min(column)
        highs[axis] = max(column)
    return (lows[0], lows[1], lows[2]), (highs[0], highs[1], highs[2])


def _scan(
    inspected: InspectedGlb,
    accessors: Sequence[_Accessor],
    meshes: Sequence[Sequence[_Primitive]],
) -> dict[int, tuple[tuple[float, float, float], tuple[float, float, float]]]:
    """P2: every value the scene draws is finite and every index names a vertex. Returns boxes."""
    boxes: dict[int, tuple[tuple[float, float, float], tuple[float, float, float]]] = {}
    checked: set[int] = set()
    used = {instance.mesh for instance in inspected.instances}
    for mesh in sorted(used):
        for primitive in meshes[mesh]:
            for semantic, index in sorted(primitive.attributes.items()):
                if index in checked:
                    continue
                accessor = accessors[index]
                values = _values(inspected.bin_chunk, accessor)
                if semantic == "POSITION":
                    boxes[index] = _position_box(values, index)
                elif accessor.component == _FLOAT:
                    for value in values:
                        if not math.isfinite(value):
                            raise _refuse(
                                "invalid_geometry", f"accessors[{index}] holds a non-finite value"
                            )
                checked.add(index)
            if primitive.indices is not None:
                values = _values(inspected.bin_chunk, accessors[primitive.indices])
                if max(values) >= primitive.vertices:
                    raise _refuse(
                        "invalid_geometry",
                        f"accessors[{primitive.indices}] names a vertex past {primitive.vertices}",
                    )
    return boxes


def _world_box(
    inspected: InspectedGlb,
    accessors: Sequence[_Accessor],
    meshes: Sequence[Sequence[_Primitive]],
    boxes: Mapping[int, tuple[tuple[float, float, float], tuple[float, float, float]]],
    root: Sequence[float] = _IDENTITY,
) -> tuple[list[float], list[float]]:
    """P4: the scene's axis-aligned bounds, exact: boxes where a transform keeps them boxes,
    every vertex where it turns them."""
    lows = [math.inf, math.inf, math.inf]
    highs = [-math.inf, -math.inf, -math.inf]

    def include(point: tuple[float, float, float]) -> None:
        for axis in range(3):
            lows[axis] = min(lows[axis], point[axis])
            highs[axis] = max(highs[axis], point[axis])

    positions: dict[int, array[Any]] = {}
    for instance in inspected.instances:
        matrix = _multiply(root, instance.matrix)
        for primitive in meshes[instance.mesh]:
            low, high = boxes[primitive.position]
            if _axis_aligned(matrix):
                for x in (low[0], high[0]):
                    for y in (low[1], high[1]):
                        for z in (low[2], high[2]):
                            include(_point(matrix, x, y, z))
            else:
                values = positions.get(primitive.position)
                if values is None:
                    values = _values(inspected.bin_chunk, accessors[primitive.position])
                    positions[primitive.position] = values
                for offset in range(0, len(values), 3):
                    include(_point(matrix, values[offset], values[offset + 1], values[offset + 2]))
    return lows, highs


def _mm(metres: float) -> int:
    fraction = Fraction(metres) * 1000
    return round_half_down(fraction.numerator, fraction.denominator)


def _um(metres: float) -> int:
    fraction = Fraction(metres) * 1_000_000
    return round_half_down(fraction.numerator, fraction.denominator)


def _strip_extras(value: Any) -> int:
    """Remove every ``extras`` and every empty ``extensions``; count the ``extras`` removed."""
    removed = 0
    if isinstance(value, dict):
        if "extras" in value:
            del value["extras"]
            removed += 1
        if value.get("extensions") == {}:
            del value["extensions"]
        for item in value.values():
            removed += _strip_extras(item)
    elif isinstance(value, list):
        for item in value:
            removed += _strip_extras(item)
    return removed


def _pad(data: bytes, filler: bytes) -> bytes:
    remainder = len(data) % 4
    return data if remainder == 0 else data + filler * (4 - remainder)


def _container_bytes(document: Mapping[str, Any], bin_chunk: bytes) -> bytes:
    json_chunk = _pad(
        json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8"),
        b" ",
    )
    parts = [struct.pack("<II", len(json_chunk), _CHUNK_JSON), json_chunk]
    if bin_chunk:
        parts.extend((struct.pack("<II", len(bin_chunk), _CHUNK_BIN), bin_chunk))
    body = b"".join(parts)
    return struct.pack("<III", _GLTF_MAGIC, 2, 12 + len(body)) + body


def _dimensions_agree(measured: int, declared: int) -> bool:
    """Within max(2 mm, 5 %) of what the person declared, in integers."""
    return 100 * abs(measured - declared) <= max(200, 5 * declared)


def prepare_static_glb(
    payload: bytes,
    *,
    unit: str,
    expected_dimensions_mm: Mapping[str, int] | None,
    decode_image: Callable[[bytes], tuple[int, int]],
    limits: StaticGlbLimits = LIMITS,
) -> PreparedGlb:
    """Validate, measure and normalize one admitted container. Deterministic; no I/O.

    ``decode_image`` decodes one embedded image and returns its decoded size, raising on bytes it
    cannot read; the preparation worker passes :mod:`exulanica.corpus.decode`. Raises
    :class:`StaticGlbRefused` with the reason the preparation fails with.
    """
    if unit not in UNITS:
        raise ValueError(f"{unit!r} is not a declared unit")
    inspected = inspect_static_glb(payload, limits)
    document = inspected.document
    accessors, meshes = inspected.accessors, inspected.meshes
    steps: list[Mapping[str, Any]] = [
        {"step": "container", "kind": "validate", "profile": PROFILE, **inspected.facts()}
    ]

    boxes = _scan(inspected, accessors, meshes)
    steps.append(
        {
            "step": "data",
            "kind": "validate",
            "position_accessors": len(boxes),
            "rendered_vertices": inspected.counts["rendered_vertices"],
            "rendered_triangles": inspected.counts["rendered_triangles"],
        }
    )

    decoded = []
    for image in inspected.images:
        data = inspected.bin_chunk[image.offset : image.offset + image.length]
        try:
            size = decode_image(data)
        except Exception as error:  # the decoder's refusal, whatever its class
            raise _refuse(
                "invalid_image", f"images[{image.index}] does not decode: {type(error).__name__}"
            ) from None
        if tuple(size) != (image.width_px, image.height_px):
            raise _refuse(
                "invalid_image",
                f"images[{image.index}] decodes to {size[0]} by {size[1]}, not its header's "
                f"{image.width_px} by {image.height_px}",
            )
        decoded.append(image.document())
    steps.append({"step": "images", "kind": "validate", "decoded": decoded})

    lows, highs = _world_box(inspected, accessors, meshes, boxes)
    scale = UNITS[unit]
    extents = [float(Fraction(highs[axis] - lows[axis]) * scale) for axis in range(3)]
    dimensions = {"width": _mm(extents[0]), "height": _mm(extents[1]), "depth": _mm(extents[2])}
    if expected_dimensions_mm is not None:
        for name in ("width", "height", "depth"):
            if not _dimensions_agree(dimensions[name], int(expected_dimensions_mm[name])):
                raise _refuse(
                    "dimensions_disagree",
                    f"the {name} measures {dimensions[name]} mm in {unit}s and was declared "
                    f"{expected_dimensions_mm[name]} mm",
                )
    largest = max(dimensions.values())
    compatible = limits.placeable_min_extent_mm <= largest <= limits.placeable_max_extent_mm
    compatibility = (
        Compatibility(
            PLACEABLE_OBJECT_PROFILE,
            "compatible" if compatible else "incompatible",
            None if compatible else "dimensions_out_of_bounds",
        ),
    )
    # Half extents round up, so the obstacle a society reads is never smaller than the object.
    footprint = (ceil_div(dimensions["width"], 2), ceil_div(dimensions["depth"], 2))
    steps.append(
        {
            "step": "measure",
            "kind": "measure",
            "unit": unit,
            "bounds_um": {
                "min": [_um(float(Fraction(value) * scale)) for value in lows],
                "max": [_um(float(Fraction(value) * scale)) for value in highs],
            },
            "dimensions_mm": dimensions,
            "footprint_half_extents_mm": list(footprint),
            "compatibility": [item.document() for item in compatibility],
        }
    )

    output_document = copy.deepcopy(dict(document))
    extras = _strip_extras(output_document)
    original = document["asset"].get("generator")
    output_document["asset"] = {
        **{
            key: document["asset"][key]
            for key in ("copyright", "minVersion")
            if key in document["asset"]
        },
        "generator": GENERATOR,
        "version": "2.0",
    }
    rewritten = 0
    for index, (low, high) in sorted(boxes.items()):
        accessor = output_document["accessors"][index]
        exact_min, exact_max = [float(value) for value in low], [float(value) for value in high]
        if accessor.get("min") != exact_min or accessor.get("max") != exact_max:
            rewritten += 1
        accessor["min"], accessor["max"] = exact_min, exact_max
    factor = float(scale)
    translation = [
        -(factor * ((lows[0] + highs[0]) / 2)),
        -(factor * lows[1]),
        -(factor * ((lows[2] + highs[2]) / 2)),
    ]
    translation = [0.0 if value == 0 else value for value in translation]
    nodes = output_document.setdefault("nodes", [])
    nodes.append(
        {
            "children": list(inspected.roots),
            "name": "prepared-root",
            "scale": [factor, factor, factor],
            "translation": translation,
        }
    )
    scene = dict(output_document["scenes"][0])
    scene["nodes"] = [len(nodes) - 1]
    output_document["scenes"] = [scene]
    output_document["scene"] = 0
    output = _container_bytes(output_document, inspected.bin_chunk)
    steps.append(
        {
            "step": "normalize",
            "kind": "transform",
            "scale": repr(factor),
            "translation_m": [repr(value) for value in translation],
            "extras_removed": extras,
            "position_bounds_rewritten": rewritten,
            "generator_replaced": original,
            "binary_chunk": "copied",
        }
    )

    _verify_output(output, dimensions, limits)
    steps.append({"step": "output", "kind": "validate", "byte_size": len(output)})
    return PreparedGlb(
        output=output,
        output_sha256=hashlib.sha256(output).hexdigest(),
        steps=tuple(steps),
        dimensions_mm=MappingProxyType(dimensions),
        footprint_half_extents_mm=footprint,
        compatibility=compatibility,
    )


def _verify_output(output: bytes, dimensions: Mapping[str, int], limits: StaticGlbLimits) -> None:
    """P6: the output passes admission again and stands centred on its origin in metres.

    The one node normalization adds, and the one level it adds above every root, are allowed for.
    """
    widened = replace(limits, nodes=limits.nodes + 1, scene_depth=limits.scene_depth + 1)
    try:
        again = inspect_static_glb(output, widened)
    except StaticGlbRefused as error:
        raise _refuse(error.reason, f"the prepared container fails admission: {error}") from None
    boxes = _scan(again, again.accessors, again.meshes)
    lows, highs = _world_box(again, again.accessors, again.meshes, boxes)
    centre = ((lows[0] + highs[0]) / 2, lows[1], (lows[2] + highs[2]) / 2)
    if any(abs(value) > _CENTRE_TOLERANCE_M for value in centre):
        raise _refuse("invalid_geometry", "the prepared container does not stand on its origin")
    measured = {
        "width": _mm(highs[0] - lows[0]),
        "height": _mm(highs[1] - lows[1]),
        "depth": _mm(highs[2] - lows[2]),
    }
    if any(abs(measured[name] - dimensions[name]) > 1 for name in dimensions):
        raise _refuse("invalid_geometry", "the prepared container does not keep its dimensions")


@dataclass(frozen=True, slots=True)
class StaticMeshInstanceBounds:
    """One active rendered mesh's exact final-byte bounds, in glTF metres."""

    node_index: int
    mesh_index: int
    minimum: tuple[Fraction, Fraction, Fraction]
    maximum: tuple[Fraction, Fraction, Fraction]
    triangles: int
    matrix: tuple[Fraction, ...]
    local_absmax: tuple[Fraction, Fraction, Fraction]


@dataclass(frozen=True, slots=True)
class StaticMeshCoverage:
    """Pure validated geometry/resource facts, never a source authorization verdict."""

    content_sha256: str
    byte_size: int
    instances: tuple[StaticMeshInstanceBounds, ...]
    draw_calls: int
    rendered_vertices: int
    rendered_triangles: int
    decoded_texels: int


def _coverage_fraction_bound(values: Sequence[Fraction]) -> None:
    # Prevent deeply nested extreme transforms from becoming unbounded rational arithmetic.
    if any(
        max(value.numerator.bit_length(), value.denominator.bit_length()) > 4096 for value in values
    ):
        raise _refuse(
            "resource_limit_exceeded", "exact coverage transform exceeds arithmetic limit"
        )


def _coverage_local(node: Mapping[str, Any]) -> tuple[Fraction, ...]:
    """The admitted glTF transform formula evaluated on exact binary input ratios."""

    def number(value: int | float) -> Fraction:
        # glTF JSON numbers become binary64 in the renderer, including integer JSON tokens.
        return Fraction(float(value))

    if "matrix" in node:
        return tuple(number(value) for value in node["matrix"])
    tx, ty, tz = map(number, node.get("translation", (0, 0, 0)))
    x, y, z, w = map(number, node.get("rotation", (0, 0, 0, 1)))
    sx, sy, sz = map(number, node.get("scale", (1, 1, 1)))
    return (
        (1 - 2 * (y * y + z * z)) * sx,
        2 * (x * y + z * w) * sx,
        2 * (x * z - y * w) * sx,
        Fraction(0),
        2 * (x * y - z * w) * sy,
        (1 - 2 * (x * x + z * z)) * sy,
        2 * (y * z + x * w) * sy,
        Fraction(0),
        2 * (x * z + y * w) * sz,
        2 * (y * z - x * w) * sz,
        (1 - 2 * (x * x + y * y)) * sz,
        Fraction(0),
        tx,
        ty,
        tz,
        Fraction(1),
    )


def static_mesh_instance_bounds(
    payload: bytes,
    *,
    decode_image: Callable[[bytes], tuple[int, int]],
    limits: StaticGlbLimits = LIMITS,
) -> StaticMeshCoverage:
    """Validate exact final bytes and cover every indexed active-scene mesh instance.

    This never prepares or rewrites bytes. It reuses the static profile's bounded parser and full
    data checks, including nonindexed triangles. Bounds follow all parent/node transforms using
    exact rational arithmetic; accessor min/max declarations are not geometry authority. Images
    are fully decoded through the caller's existing decode site. No registry, store or cache I/O.
    """
    inspected = inspect_static_glb(payload, limits)
    _scan(inspected, inspected.accessors, inspected.meshes)
    for image in inspected.images:
        encoded = inspected.bin_chunk[image.offset : image.offset + image.length]
        try:
            measured = tuple(decode_image(encoded))
        except Exception as error:
            raise _refuse(
                "invalid_image", f"images[{image.index}] does not decode: {type(error).__name__}"
            ) from None
        if measured != (image.width_px, image.height_px):
            raise _refuse("invalid_image", f"images[{image.index}] decoded size differs")
    nodes = inspected.document["nodes"]
    identity = tuple(Fraction(i % 5 == 0) for i in range(16))
    stack = [(number, identity) for number in reversed(inspected.roots)]
    result = []
    arrays: dict[int, array[Any]] = {}
    while stack:
        number, parent = stack.pop()
        node = nodes[number]
        local = _coverage_local(node)
        _coverage_fraction_bound(local)
        world = tuple(
            sum(parent[k * 4 + row] * local[column * 4 + k] for k in range(4))
            for column in range(4)
            for row in range(4)
        )
        _coverage_fraction_bound(world)
        if "mesh" in node:
            mesh = node["mesh"]
            lows: list[Fraction | None] = [None, None, None]
            highs: list[Fraction | None] = [None, None, None]
            triangles = 0
            local_absmax = [Fraction(0)] * 3
            for primitive in inspected.meshes[mesh]:
                for index in (primitive.position, primitive.indices):
                    if index is not None and index not in arrays:
                        arrays[index] = _values(inspected.bin_chunk, inspected.accessors[index])
                coordinates = arrays[primitive.position]
                indices = (
                    range(primitive.vertices)
                    if primitive.indices is None
                    else arrays[primitive.indices]
                )
                triangles += primitive.triangles
                for index in set(indices):
                    p = tuple(Fraction(coordinates[index * 3 + k]) for k in range(3))
                    for axis in range(3):
                        local_absmax[axis] = max(local_absmax[axis], abs(p[axis]))
                    transformed = tuple(
                        sum(world[k + r * 4] * p[r] for r in range(3)) + world[k + 12]
                        for k in range(3)
                    )
                    _coverage_fraction_bound(transformed)
                    for k, value in enumerate(transformed):
                        lows[k] = value if lows[k] is None else min(lows[k], value)
                        highs[k] = value if highs[k] is None else max(highs[k], value)
            if any(v is None for v in (*lows, *highs)):
                raise _refuse("invalid_geometry", "an active mesh has no covered vertex")
            result.append(
                StaticMeshInstanceBounds(
                    number, mesh, tuple(lows), tuple(highs), triangles, world, tuple(local_absmax)
                )
            )
        stack.extend((child, world) for child in reversed(node.get("children", [])))
    counts = inspected.counts
    return StaticMeshCoverage(
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        tuple(result),
        counts["draw_calls"],
        counts["rendered_vertices"],
        counts["rendered_triangles"],
        counts["texels"],
    )
