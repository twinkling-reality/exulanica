"""The static glTF binary admission's checks, one part of the container at a time.

Each reads the JSON chunk and the image headers only and changes nothing: the chunks and the JSON
document, the extensions it declares, the asset, buffers and views, accessors, images (PNG and JPEG
sizes from their headers), textures and materials, meshes and their primitives, nodes and the scene
graph, and where every primitive's instances stand. Each refuses by name
(:class:`~exulanica.world.static_glb_format.StaticGlbRefused`) before the loop its bound limits.
:func:`~exulanica.world.static_glb.inspect_static_glb` runs them in order.
"""

from __future__ import annotations

import json
import math
import struct
from collections.abc import Iterator, Mapping, Sequence
from types import MappingProxyType
from typing import Any, Final

from exulanica.world.asset_import import MAX_ASSET_BYTES
from exulanica.world.static_glb_format import (
    _ATTRIBUTE_FORMATS,
    _CHUNK_BIN,
    _CHUNK_JSON,
    _CODECS,
    _COMPONENTS,
    _FLOAT,
    _GLTF_MAGIC,
    _IMAGE_MEDIA,
    _INDEX_FORMATS,
    _JPEG_FRAMES,
    _MAG_FILTERS,
    _MIN_FILTERS,
    _NOT_STATIC,
    _PROPERTIES,
    _TRIANGLES,
    _UNIT_QUATERNION,
    _UNIVERSAL,
    _WIDTHS,
    _WRAPS,
    MAX_JSON_BYTES,
    ImageHeader,
    StaticGlbLimits,
    StaticGlbRefused,
    _Accessor,
    _Instance,
    _Primitive,
)

# -- the container -------------------------------------------------------------------------------


def _refuse(reason: str, message: str) -> StaticGlbRefused:
    return StaticGlbRefused(reason, message)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _refuse("malformed_container", f"the JSON chunk states {key!r} twice")
        result[key] = value
    return result


def _no_constant(name: str) -> Any:
    raise _refuse("malformed_container", f"the JSON chunk holds {name}, which JSON does not")


def _chunks(payload: bytes) -> tuple[bytes, bytes | None]:
    """The JSON chunk and the binary chunk (or None), exactly as stored."""
    if len(payload) > MAX_ASSET_BYTES:
        raise _refuse("resource_limit_exceeded", f"a container is at most {MAX_ASSET_BYTES} bytes")
    if len(payload) < 20 or len(payload) % 4:
        raise _refuse("malformed_container", "a container is at least 20 bytes in whole words")
    if struct.unpack_from("<III", payload) != (_GLTF_MAGIC, 2, len(payload)):
        raise _refuse("malformed_container", "not a glTF 2.0 binary of its stated length")
    chunks: list[tuple[int, bytes]] = []
    offset = 12
    while offset < len(payload):
        if len(chunks) == 2:
            raise _refuse("malformed_container", "a container holds at most a JSON and a BIN chunk")
        if offset + 8 > len(payload):
            raise _refuse("malformed_container", "a chunk header is cut short")
        length, kind = struct.unpack_from("<II", payload, offset)
        offset += 8
        if length % 4 or offset + length > len(payload):
            raise _refuse("malformed_container", "a chunk's length is not inside the container")
        chunks.append((kind, payload[offset : offset + length]))
        offset += length
    if not chunks or chunks[0][0] != _CHUNK_JSON:
        raise _refuse("malformed_container", "the first chunk must be JSON")
    if len(chunks) == 2 and chunks[1][0] != _CHUNK_BIN:
        raise _refuse("malformed_container", "the second chunk must be BIN")
    if not 0 < len(chunks[0][1]) <= MAX_JSON_BYTES:
        raise _refuse("resource_limit_exceeded", f"the JSON chunk is over {MAX_JSON_BYTES} bytes")
    return chunks[0][1], chunks[1][1] if len(chunks) == 2 else None


def _document(json_chunk: bytes) -> dict[str, Any]:
    try:
        text = json_chunk.decode("utf-8")
        document = json.loads(text, object_pairs_hook=_unique_keys, parse_constant=_no_constant)
    except StaticGlbRefused:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise _refuse("malformed_container", f"the JSON chunk does not parse: {error}") from None
    if not isinstance(document, dict):
        raise _refuse("malformed_container", "the JSON chunk is not an object")
    return document


def _walk(value: Any, path: str) -> Iterator[tuple[str, str, Any]]:
    """Every ``(path, key, value)`` in the document outside ``extras``, which nothing reads."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "extras":
                continue
            yield path, key, item
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


def _declared_extensions(document: Mapping[str, Any]) -> None:
    required = document.get("extensionsRequired", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise _refuse("malformed_container", "extensionsRequired is a list of names")
    used = document.get("extensionsUsed", [])
    if not isinstance(used, list) or any(not isinstance(item, str) for item in used):
        raise _refuse("malformed_container", "extensionsUsed is a list of names")
    codecs = sorted(_CODECS.intersection(required) | _CODECS.intersection(used))
    if codecs:
        raise _refuse(
            "compressed_content",
            f"{', '.join(codecs)} needs a decoder this profile does not admit",
        )
    if required:
        raise _refuse("required_extension", f"the container requires {', '.join(sorted(required))}")
    if used:
        raise _refuse(
            "extension_not_admitted",
            f"this profile admits no glTF extension, and the container uses "
            f"{', '.join(sorted(used))}",
        )
    for path, key, value in _walk(document, "$"):
        if key == "uri":
            raise _refuse(
                "external_reference",
                f"{path}.uri names something outside the container; every resource is embedded",
            )
        if key == "extensions" and value not in ({}, None):
            raise _refuse("extension_not_admitted", f"{path} states an extension")


# -- typed reads ---------------------------------------------------------------------------------


def _int(value: Any, where: str, *, low: int = 0, high: int | None = None) -> int:
    if type(value) is not int or value < low or (high is not None and value > high):
        bound = f"{low} or more" if high is None else f"{low} to {high}"
        raise _refuse("malformed_container", f"{where} is an integer {bound}")
    return value


def _number(value: Any, where: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise _refuse("malformed_container", f"{where} is a finite number")
    return float(value)


def _numbers(value: Any, where: str, count: int) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != count:
        raise _refuse("malformed_container", f"{where} is {count} numbers")
    return tuple(_number(item, f"{where}[{index}]") for index, item in enumerate(value))


def _unit_interval(value: Any, where: str) -> None:
    number = _number(value, where)
    if not 0 <= number <= 1:
        raise _refuse("malformed_container", f"{where} is between 0 and 1")


def _objects(document: Mapping[str, Any], name: str, limit: int) -> list[dict[str, Any]]:
    value = document.get(name, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise _refuse("malformed_container", f"{name} is a list of objects")
    if len(value) > limit:
        raise _refuse(
            "resource_limit_exceeded", f"{len(value)} {name} is over this profile's {limit}"
        )
    return value


def _properties(item: Mapping[str, Any], kind: str, where: str) -> None:
    for key in item:
        if key in _UNIVERSAL or key in _PROPERTIES[kind]:
            continue
        if key in _NOT_STATIC:
            raise _refuse("not_static", f"{where}.{key} makes the object move or deform")
        if key == "camera":
            raise _refuse("unsupported_feature", f"{where} carries a camera")
        if key == "sparse":
            raise _refuse("unsupported_feature", f"{where} is a sparse accessor")
        raise _refuse("unsupported_feature", f"{where}.{key} is not a property this profile reads")
    name = item.get("name")
    if name is not None and not isinstance(name, str):
        raise _refuse("malformed_container", f"{where}.name is text")


def _index(value: Any, where: str, count: int) -> int:
    if type(value) is not int or not 0 <= value < count:
        raise _refuse("malformed_container", f"{where} names no entry of its list")
    return value


# -- the checks ----------------------------------------------------------------------------------


def _check_asset(document: Mapping[str, Any]) -> None:
    asset = document.get("asset")
    if not isinstance(asset, dict):
        raise _refuse("malformed_container", "the container states no asset")
    _properties(asset, "asset", "asset")
    if asset.get("version") != "2.0":
        raise _refuse("malformed_container", "asset.version must be 2.0")
    for key in ("copyright", "generator", "minVersion"):
        if key in asset and not isinstance(asset[key], str):
            raise _refuse("malformed_container", f"asset.{key} is text")
    if "minVersion" in asset and asset["minVersion"] != "2.0":
        raise _refuse("unsupported_feature", "asset.minVersion names a version after 2.0")


def _check_buffers(
    document: Mapping[str, Any], bin_chunk: bytes | None, limits: StaticGlbLimits
) -> tuple[list[dict[str, Any]], int]:
    buffers = _objects(document, "buffers", 1)
    if buffers and bin_chunk is None:
        raise _refuse("malformed_container", "a buffer is declared and the container has no BIN")
    buffer_length = 0
    for number, buffer in enumerate(buffers):
        _properties(buffer, "buffer", f"buffers[{number}]")
        buffer_length = _int(
            buffer.get("byteLength"),
            f"buffers[{number}].byteLength",
            low=1,
            high=len(bin_chunk or b""),
        )
    views = _objects(document, "bufferViews", limits.buffer_views)
    for number, view in enumerate(views):
        where = f"bufferViews[{number}]"
        _properties(view, "bufferView", where)
        _index(view.get("buffer"), f"{where}.buffer", len(buffers))
        offset = _int(view.get("byteOffset", 0), f"{where}.byteOffset")
        length = _int(view.get("byteLength"), f"{where}.byteLength", low=1)
        if offset + length > buffer_length:
            raise _refuse("malformed_container", f"{where} runs past its buffer")
        if "byteStride" in view:
            stride = _int(view["byteStride"], f"{where}.byteStride", low=4, high=252)
            if stride % 4:
                raise _refuse("malformed_container", f"{where}.byteStride is a multiple of 4")
        if "target" in view and view["target"] not in (34962, 34963):
            raise _refuse("malformed_container", f"{where}.target is a buffer target")
    return views, buffer_length


def _check_accessors(
    document: Mapping[str, Any], views: list[dict[str, Any]], limits: StaticGlbLimits
) -> list[_Accessor]:
    accessors = _objects(document, "accessors", limits.accessors)
    checked: list[_Accessor] = []
    for number, accessor in enumerate(accessors):
        where = f"accessors[{number}]"
        _properties(accessor, "accessor", where)
        if "bufferView" not in accessor:
            raise _refuse("unsupported_feature", f"{where} has no buffer view")
        view = views[_index(accessor["bufferView"], f"{where}.bufferView", len(views))]
        component = accessor.get("componentType")
        if component not in _COMPONENTS or type(component) is not int:
            raise _refuse("malformed_container", f"{where}.componentType is a glTF component type")
        kind = accessor.get("type")
        if kind not in _WIDTHS:
            raise _refuse("unsupported_feature", f"{where}.type {kind!r} is not a vector or scalar")
        normalized = accessor.get("normalized", False)
        if type(normalized) is not bool:
            raise _refuse("malformed_container", f"{where}.normalized is true or false")
        if normalized and component in (5125, _FLOAT):
            raise _refuse("malformed_container", f"{where} normalizes a type that cannot be")
        count = _int(accessor.get("count"), f"{where}.count", low=1)
        size = _COMPONENTS[component][1]
        element = size * _WIDTHS[kind]
        offset = _int(accessor.get("byteOffset", 0), f"{where}.byteOffset")
        base = view.get("byteOffset", 0) + offset
        if base % size:
            raise _refuse("malformed_container", f"{where} is not aligned to its component size")
        stride = view.get("byteStride", element)
        if stride < element:
            raise _refuse("malformed_container", f"{where} is wider than its view's stride")
        if offset + stride * (count - 1) + element > view["byteLength"]:
            raise _refuse("malformed_container", f"{where} runs past its buffer view")
        for bound in ("min", "max"):
            if bound in accessor:
                _numbers(accessor[bound], f"{where}.{bound}", _WIDTHS[kind])
        checked.append(_Accessor(number, kind, component, normalized, count, base, stride, element))
    return checked


def _check_images(
    document: Mapping[str, Any],
    views: list[dict[str, Any]],
    bin_chunk: bytes | None,
    limits: StaticGlbLimits,
) -> tuple[ImageHeader, ...]:
    images = _objects(document, "images", limits.images)
    headers: list[ImageHeader] = []
    texels = 0
    for number, image in enumerate(images):
        where = f"images[{number}]"
        _properties(image, "image", where)
        if "bufferView" not in image:
            raise _refuse("malformed_container", f"{where} names no embedded buffer view")
        view = views[_index(image["bufferView"], f"{where}.bufferView", len(views))]
        if "byteStride" in view:
            raise _refuse("malformed_container", f"{where}'s buffer view has a stride")
        media_type = image.get("mimeType")
        if media_type not in _IMAGE_MEDIA:
            raise _refuse("unsupported_feature", f"{where}.mimeType is image/png or image/jpeg")
        start = view.get("byteOffset", 0)
        data = (bin_chunk or b"")[start : start + view["byteLength"]]
        width, height = _image_size(data, media_type, where)
        if max(width, height) > limits.texture_side_px:
            raise _refuse(
                "resource_limit_exceeded",
                f"{where} is {width} by {height}; a side is at most {limits.texture_side_px} px",
            )
        texels += width * height
        if texels > limits.texels:
            raise _refuse(
                "resource_limit_exceeded",
                f"the images hold more than {limits.texels} texels",
            )
        headers.append(ImageHeader(number, media_type, width, height, start, view["byteLength"]))
    return tuple(headers)


def _image_size(data: bytes, media_type: str, where: str) -> tuple[int, int]:
    """Width and height from the header alone. No pixel is decoded here."""
    if not data.startswith(_IMAGE_MEDIA[media_type]):
        raise _refuse("invalid_image", f"{where} is not the {media_type} it says it is")
    if media_type == "image/png":
        if len(data) < 33 or data[12:16] != b"IHDR" or struct.unpack(">I", data[8:12])[0] != 13:
            raise _refuse("invalid_image", f"{where} has no PNG header")
        width, height = struct.unpack(">II", data[16:24])
    else:
        width, height = _jpeg_size(data, where)
    if width < 1 or height < 1:
        raise _refuse("invalid_image", f"{where} states an empty frame")
    return width, height


def _jpeg_size(data: bytes, where: str) -> tuple[int, int]:
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            raise _refuse("invalid_image", f"{where} has a broken JPEG marker")
        marker = data[offset + 1]
        if marker == 0xFF:
            offset += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        if marker in (0xD9, 0xDA):
            break
        length = struct.unpack(">H", data[offset + 2 : offset + 4])[0]
        if length < 2 or offset + 2 + length > len(data):
            raise _refuse("invalid_image", f"{where} has a JPEG segment past its end")
        if marker in _JPEG_FRAMES:
            if length < 7:
                raise _refuse("invalid_image", f"{where} has a short JPEG frame header")
            height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
            return width, height
        offset += 2 + length
    raise _refuse("invalid_image", f"{where} states no JPEG frame size")


def _texture_info(value: Any, where: str, kind: str, textures: int) -> None:
    if not isinstance(value, dict):
        raise _refuse("malformed_container", f"{where} is an object")
    _properties(value, kind, where)
    _index(value.get("index"), f"{where}.index", textures)
    if "texCoord" in value:
        _int(value["texCoord"], f"{where}.texCoord", high=1)
    if "scale" in value:
        _number(value["scale"], f"{where}.scale")
    if "strength" in value:
        _unit_interval(value["strength"], f"{where}.strength")


def _check_materials(
    document: Mapping[str, Any], images: int, limits: StaticGlbLimits
) -> tuple[int, int]:
    samplers = _objects(document, "samplers", limits.samplers)
    for number, sampler in enumerate(samplers):
        where = f"samplers[{number}]"
        _properties(sampler, "sampler", where)
        for key, allowed in (
            ("magFilter", _MAG_FILTERS),
            ("minFilter", _MIN_FILTERS),
            ("wrapS", _WRAPS),
            ("wrapT", _WRAPS),
        ):
            if key in sampler and (type(sampler[key]) is not int or sampler[key] not in allowed):
                raise _refuse("malformed_container", f"{where}.{key} is not a glTF sampler value")
    textures = _objects(document, "textures", limits.textures)
    for number, texture in enumerate(textures):
        where = f"textures[{number}]"
        _properties(texture, "texture", where)
        if "source" not in texture:
            raise _refuse("unsupported_feature", f"{where} names no image")
        _index(texture["source"], f"{where}.source", images)
        if "sampler" in texture:
            _index(texture["sampler"], f"{where}.sampler", len(samplers))
    materials = _objects(document, "materials", limits.materials)
    for number, material in enumerate(materials):
        where = f"materials[{number}]"
        _properties(material, "material", where)
        pbr = material.get("pbrMetallicRoughness")
        if pbr is not None:
            if not isinstance(pbr, dict):
                raise _refuse("malformed_container", f"{where}.pbrMetallicRoughness is an object")
            _properties(pbr, "pbrMetallicRoughness", f"{where}.pbrMetallicRoughness")
            if "baseColorFactor" in pbr:
                for index, value in enumerate(
                    _numbers(pbr["baseColorFactor"], f"{where}.baseColorFactor", 4)
                ):
                    _unit_interval(value, f"{where}.baseColorFactor[{index}]")
            for key in ("metallicFactor", "roughnessFactor"):
                if key in pbr:
                    _unit_interval(pbr[key], f"{where}.{key}")
            for key in ("baseColorTexture", "metallicRoughnessTexture"):
                if key in pbr:
                    _texture_info(pbr[key], f"{where}.{key}", "textureInfo", len(textures))
        for key, kind in (
            ("normalTexture", "normalTextureInfo"),
            ("occlusionTexture", "occlusionTextureInfo"),
            ("emissiveTexture", "textureInfo"),
        ):
            if key in material:
                _texture_info(material[key], f"{where}.{key}", kind, len(textures))
        if "emissiveFactor" in material:
            for index, value in enumerate(
                _numbers(material["emissiveFactor"], f"{where}.emissiveFactor", 3)
            ):
                _unit_interval(value, f"{where}.emissiveFactor[{index}]")
        if material.get("alphaMode", "OPAQUE") not in ("OPAQUE", "MASK", "BLEND"):
            raise _refuse("malformed_container", f"{where}.alphaMode is OPAQUE, MASK or BLEND")
        if (
            "alphaCutoff" in material
            and _number(material["alphaCutoff"], f"{where}.alphaCutoff") < 0
        ):
            raise _refuse("malformed_container", f"{where}.alphaCutoff is not negative")
        if "doubleSided" in material and type(material["doubleSided"]) is not bool:
            raise _refuse("malformed_container", f"{where}.doubleSided is true or false")
    return len(textures), len(materials)


def _check_meshes(
    document: Mapping[str, Any],
    accessors: list[_Accessor],
    materials: int,
    limits: StaticGlbLimits,
) -> list[list[_Primitive]]:
    meshes = _objects(document, "meshes", limits.meshes)
    checked: list[list[_Primitive]] = []
    total = 0
    for number, mesh in enumerate(meshes):
        where = f"meshes[{number}]"
        _properties(mesh, "mesh", where)
        primitives = mesh.get("primitives")
        if not isinstance(primitives, list) or not primitives:
            raise _refuse("malformed_container", f"{where}.primitives is a non-empty list")
        total += len(primitives)
        if total > limits.primitives:
            raise _refuse(
                "resource_limit_exceeded",
                f"the meshes hold more than this profile's {limits.primitives} primitives",
            )
        mesh_primitives: list[_Primitive] = []
        for index, primitive in enumerate(primitives):
            mesh_primitives.append(
                _check_primitive(primitive, f"{where}.primitives[{index}]", accessors, materials)
            )
        checked.append(mesh_primitives)
    return checked


def _check_primitive(
    primitive: Any, where: str, accessors: list[_Accessor], materials: int
) -> _Primitive:
    if not isinstance(primitive, dict):
        raise _refuse("malformed_container", f"{where} is an object")
    _properties(primitive, "primitive", where)
    if primitive.get("mode", _TRIANGLES) != _TRIANGLES:
        raise _refuse("unsupported_feature", f"{where} draws something other than triangles")
    if "material" in primitive:
        _index(primitive["material"], f"{where}.material", materials)
    attributes = primitive.get("attributes")
    if not isinstance(attributes, dict) or "POSITION" not in attributes:
        raise _refuse("malformed_container", f"{where} states no POSITION attribute")
    counts: set[int] = set()
    resolved: dict[str, int] = {}
    for semantic, value in attributes.items():
        if semantic.startswith(("JOINTS_", "WEIGHTS_")):
            raise _refuse("not_static", f"{where} is skinned by {semantic}")
        formats = _ATTRIBUTE_FORMATS.get(semantic)
        if formats is None:
            raise _refuse("unsupported_feature", f"{where}.attributes.{semantic} is not read")
        accessor = accessors[_index(value, f"{where}.attributes.{semantic}", len(accessors))]
        if accessor.format not in formats:
            raise _refuse(
                "malformed_container", f"{where}.attributes.{semantic} has the wrong format"
            )
        counts.add(accessor.count)
        resolved[semantic] = accessor.index
    if len(counts) != 1:
        raise _refuse("malformed_container", f"{where}'s attributes differ in count")
    vertices = counts.pop()
    indices: int | None = None
    if "indices" in primitive:
        accessor = accessors[_index(primitive["indices"], f"{where}.indices", len(accessors))]
        if accessor.format not in _INDEX_FORMATS:
            raise _refuse("malformed_container", f"{where}.indices has the wrong format")
        if accessor.stride != accessor.element:
            raise _refuse("malformed_container", f"{where}.indices are strided")
        if accessor.count % 3:
            raise _refuse("invalid_geometry", f"{where}.indices is not whole triangles")
        indices = accessor.index
        triangles = accessor.count // 3
    else:
        if vertices % 3:
            raise _refuse("invalid_geometry", f"{where} is not whole triangles")
        triangles = vertices // 3
    return _Primitive(
        resolved["POSITION"], MappingProxyType(resolved), indices, vertices, triangles
    )


def _check_nodes(
    document: Mapping[str, Any], meshes: int, limits: StaticGlbLimits
) -> list[dict[str, Any]]:
    nodes = _objects(document, "nodes", limits.nodes)
    for number, node in enumerate(nodes):
        where = f"nodes[{number}]"
        _properties(node, "node", where)
        if "mesh" in node:
            _index(node["mesh"], f"{where}.mesh", meshes)
        children = node.get("children", [])
        if not isinstance(children, list):
            raise _refuse("malformed_container", f"{where}.children is a list")
        for index, child in enumerate(children):
            _index(child, f"{where}.children[{index}]", len(nodes))
        if len(set(children)) != len(children):
            raise _refuse("malformed_container", f"{where} names a child twice")
        if "matrix" in node:
            if {"rotation", "scale", "translation"} & node.keys():
                raise _refuse("malformed_container", f"{where} states a matrix and TRS both")
            matrix = _numbers(node["matrix"], f"{where}.matrix", 16)
            if (matrix[3], matrix[7], matrix[11], matrix[15]) != (0.0, 0.0, 0.0, 1.0):
                raise _refuse("malformed_container", f"{where}.matrix is not an affine transform")
        if "rotation" in node:
            rotation = _numbers(node["rotation"], f"{where}.rotation", 4)
            if abs(math.sqrt(sum(value * value for value in rotation)) - 1) > _UNIT_QUATERNION:
                raise _refuse("malformed_container", f"{where}.rotation is not a unit quaternion")
        for key in ("scale", "translation"):
            if key in node:
                _numbers(node[key], f"{where}.{key}", 3)
    return nodes


def _roots(document: Mapping[str, Any], nodes: list[dict[str, Any]]) -> tuple[int, ...]:
    scenes = _objects(document, "scenes", 1 << 16)
    if len(scenes) > 1:
        raise _refuse("unsupported_feature", f"the container holds {len(scenes)} scenes, not one")
    if not scenes:
        raise _refuse("invalid_geometry", "the container states no scene to draw")
    if "scene" in document:
        _index(document["scene"], "scene", len(scenes))
    scene = scenes[0]
    _properties(scene, "scene", "scenes[0]")
    roots = scene.get("nodes")
    if not isinstance(roots, list) or not roots:
        raise _refuse("invalid_geometry", "the scene names no node")
    for index, root in enumerate(roots):
        _index(root, f"scenes[0].nodes[{index}]", len(nodes))
    if len(set(roots)) != len(roots):
        raise _refuse("malformed_container", "the scene names a node twice")
    return tuple(roots)


def _check_graph(
    nodes: list[dict[str, Any]], roots: tuple[int, ...], limits: StaticGlbLimits
) -> None:
    parent: dict[int, int] = {}
    for number, node in enumerate(nodes):
        for child in node.get("children", []):
            if child in parent:
                raise _refuse("malformed_container", f"nodes[{child}] has two parents")
            if child == number:
                raise _refuse("malformed_container", f"nodes[{number}] is its own child")
            parent[child] = number
    for root in roots:
        if root in parent:
            raise _refuse("malformed_container", f"scene root nodes[{root}] has a parent")
    for number in range(len(nodes)):
        seen = {number}
        cursor = number
        depth = 1
        while cursor in parent:
            cursor = parent[cursor]
            depth += 1
            if cursor in seen:
                raise _refuse("malformed_container", "the node hierarchy has a cycle")
            seen.add(cursor)
            if depth > limits.scene_depth:
                raise _refuse(
                    "resource_limit_exceeded",
                    f"the node hierarchy is deeper than this profile's {limits.scene_depth}",
                )


# -- matrices ------------------------------------------------------------------------------------

_IDENTITY: Final = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def _multiply(a: Sequence[float], b: Sequence[float]) -> tuple[float, ...]:
    """``a @ b`` for column-major 4x4 matrices."""
    return tuple(
        sum(a[k * 4 + row] * b[column * 4 + k] for k in range(4))
        for column in range(4)
        for row in range(4)
    )


def _local(node: Mapping[str, Any]) -> tuple[float, ...]:
    if "matrix" in node:
        return tuple(float(value) for value in node["matrix"])
    tx, ty, tz = (float(value) for value in node.get("translation", (0, 0, 0)))
    qx, qy, qz, qw = (float(value) for value in node.get("rotation", (0, 0, 0, 1)))
    sx, sy, sz = (float(value) for value in node.get("scale", (1, 1, 1)))
    rotation = (
        1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy + qz * qw), 2 * (qx * qz - qy * qw),
        2 * (qx * qy - qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz + qx * qw),
        2 * (qx * qz + qy * qw), 2 * (qy * qz - qx * qw), 1 - 2 * (qx * qx + qy * qy),
    )  # fmt: skip
    return (
        rotation[0] * sx, rotation[1] * sx, rotation[2] * sx, 0.0,
        rotation[3] * sy, rotation[4] * sy, rotation[5] * sy, 0.0,
        rotation[6] * sz, rotation[7] * sz, rotation[8] * sz, 0.0,
        tx, ty, tz, 1.0,
    )  # fmt: skip


def _axis_aligned(matrix: Sequence[float]) -> bool:
    """Whether the linear part maps each axis onto one axis, so a box maps exactly onto a box."""
    for column in range(3):
        if sum(1 for row in range(3) if matrix[column * 4 + row] != 0.0) > 1:
            return False
    return True


def _point(matrix: Sequence[float], x: float, y: float, z: float) -> tuple[float, float, float]:
    return (
        matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
        matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
        matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
    )


def _instances(
    nodes: list[dict[str, Any]],
    roots: tuple[int, ...],
    meshes: list[list[_Primitive]],
    limits: StaticGlbLimits,
) -> tuple[tuple[_Instance, ...], dict[str, int]]:
    instances: list[_Instance] = []
    draws = vertices = triangles = 0
    stack: list[tuple[int, tuple[float, ...]]] = [(root, _IDENTITY) for root in reversed(roots)]
    while stack:
        number, parent = stack.pop()
        node = nodes[number]
        world = _multiply(parent, _local(node))
        if "mesh" in node:
            instances.append(_Instance(number, node["mesh"], world))
            for primitive in meshes[node["mesh"]]:
                draws += 1
                vertices += primitive.vertices
                triangles += primitive.triangles
            for name, value, limit in (
                ("draw calls", draws, limits.draw_calls),
                ("vertices", vertices, limits.rendered_vertices),
                ("triangles", triangles, limits.rendered_triangles),
            ):
                if value > limit:
                    raise _refuse(
                        "resource_limit_exceeded",
                        f"the scene draws more than this profile's {limit} {name}",
                    )
        stack.extend((child, world) for child in reversed(node.get("children", [])))
    if not triangles:
        raise _refuse("invalid_geometry", "the scene draws no triangle")
    return tuple(instances), {
        "draw_calls": draws,
        "rendered_vertices": vertices,
        "rendered_triangles": triangles,
    }
