"""Shapes of a form sent to a model under a strict schema, checked without a model.

Imported by the tests of each drafter whose form is sent with ``strict: true``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any


def _resolved(schema: Mapping[str, Any], root: Mapping[str, Any]) -> Mapping[str, Any]:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    *_, name = reference.split("/")
    return root["$defs"][name]


def _objects(
    schema: Mapping[str, Any], root: Mapping[str, Any], path: str, seen: set[str]
) -> Iterator[tuple[str, Mapping[str, Any]]]:
    reference = schema.get("$ref")
    if reference is not None:
        if reference in seen:
            return
        seen = seen | {reference}
    schema = _resolved(schema, root)
    if "properties" in schema:
        yield path, schema
        for name, child in schema["properties"].items():
            yield from _objects(child, root, f"{path}.{name}", seen)
    for key in ("items", "additionalProperties"):
        child = schema.get(key)
        if isinstance(child, Mapping):
            yield from _objects(child, root, f"{path}[]", seen)
    for key in ("anyOf", "oneOf", "allOf"):
        for index, child in enumerate(schema.get(key) or ()):
            yield from _objects(child, root, f"{path}|{index}", seen)


def _is_array(schema: Mapping[str, Any], root: Mapping[str, Any]) -> bool:
    schema = _resolved(schema, root)
    if schema.get("type") == "array" or (
        isinstance(schema.get("type"), list) and "array" in schema["type"]
    ):
        return True
    return any(_is_array(choice, root) for choice in schema.get("anyOf") or ())


def arrays_followed_by_a_property(schema: Mapping[str, Any]) -> list[str]:
    """Every array property, at every level, that another property follows in its object.

    A model writes properties in the order the schema lists them. After an array that names
    something, a following property needs a comma, and a reply that put a line break there instead
    can write nothing but whitespace: the schema allows only the comma or whitespace at that point.
    An array listed last can only be followed by its object's closing brace.
    """
    found: list[str] = []
    for path, obj in _objects(schema, schema, "$", set()):
        names = list(obj["properties"])
        for position, name in enumerate(names[:-1]):
            if _is_array(obj["properties"][name], schema):
                found.append(f"{path}.{name} (followed by {names[position + 1]})")
    return found


def properties_after_an_array(schema: Mapping[str, Any]) -> list[str]:
    """Every property, at every level, that is not an array and follows an array in its object.

    For a form with several lists in one object, where only one can be listed last: listed after
    every other property, a list is followed only by another list or its object's closing brace.
    """
    found: list[str] = []
    for path, obj in _objects(schema, schema, "$", set()):
        names = list(obj["properties"])
        arrays = [_is_array(obj["properties"][name], schema) for name in names]
        if True in arrays:
            first = arrays.index(True)
            found.extend(
                f"{path}.{name}"
                for name, is_array in zip(names[first:], arrays[first:], strict=True)
                if not is_array
            )
    return found
