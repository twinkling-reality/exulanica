"""What a server says it supports, read from the server rather than written into this client.

Three reads answer "which edits can I make to this world, and with what", and each is the
server's own statement:

*   The OpenAPI document (``GET /openapi.json``) names every operation. An edit of an authored
    version is an operation whose request body carries ``base_state_sha256``, the version state the
    edit was made against, and whose answer is the whole version, the same schema
    ``GET /world/versions/{version_id}`` returns. Both halves matter: society routes also name a
    ``base_state_sha256``, of the society's state, and answer with something else.
*   ``GET /world/behaviours`` lists the reviewed behaviours an object may be given, each with its
    parameters' kinds and bounds.
*   ``GET /world/assets`` lists the reviewed assets an object may be made from, each with whether
    its bytes are present on that server.

A parameter kind this client does not know is reported as unsupported rather than guessed at.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "VERSION_READ",
    "Behaviour",
    "Operation",
    "parse_behaviour_identity",
    "reviewed_behaviours",
    "version_edits",
]

#: The read that answers with one authored version. Its answer schema is what marks an edit.
VERSION_READ = ("GET", "/world/versions/{version_id}")
#: The field every authored edit carries: the version state it was made against.
_EDIT_BASE = "base_state_sha256"
_ACCEPTED = ("200", "201")


@dataclass(frozen=True)
class Operation:
    """One operation a server documents, by the method and path a client sends it to."""

    method: str
    path: str
    operation_id: str
    summary: str


def _json_schema_ref(content: Mapping[str, Any] | None) -> str | None:
    schema = (content or {}).get("application/json", {}).get("schema", {})
    reference = schema.get("$ref")
    return reference if isinstance(reference, str) else None


def _properties(reference: str | None, schemas: Mapping[str, Any]) -> set[str]:
    if reference is None:
        return set()
    schema = schemas.get(reference.rsplit("/", 1)[-1], {})
    return set(schema.get("properties", {}))


def version_edits(openapi: Mapping[str, Any]) -> list[Operation]:
    """Every operation the server documents as an edit of an authored version, in its own order."""
    paths = openapi.get("paths", {})
    schemas = openapi.get("components", {}).get("schemas", {})
    method, path = VERSION_READ
    read = paths.get(path, {}).get(method.lower())
    if read is None:
        return []
    version_schema = _json_schema_ref(read.get("responses", {}).get("200", {}).get("content"))
    found: list[Operation] = []
    for route, item in paths.items():
        for verb, operation in item.items():
            body = _json_schema_ref(operation.get("requestBody", {}).get("content"))
            answers = {
                _json_schema_ref(operation.get("responses", {}).get(status, {}).get("content"))
                for status in _ACCEPTED
            }
            if _EDIT_BASE in _properties(body, schemas) and version_schema in answers:
                found.append(
                    Operation(
                        verb.upper(),
                        route,
                        operation.get("operationId", ""),
                        operation.get("summary", ""),
                    )
                )
    return found


@dataclass(frozen=True)
class Behaviour:
    """One reviewed behaviour and the bounds the server holds each of its parameters to."""

    key: str
    version: int
    parameters: Mapping[str, Mapping[str, Any]]

    @property
    def identity(self) -> str:
        return f"{self.key}@{self.version}"

    def defaults(self) -> dict[str, Any]:
        """The value the server's registry declares for each parameter when none is chosen."""
        return {name: bound["default"] for name, bound in self.parameters.items()}

    def problems(self, values: Mapping[str, Any]) -> list[str]:
        """Why ``values`` would be refused, in the registry's terms, or nothing when they fit."""
        found = [
            f"{name} is not a parameter of {self.identity}"
            for name in values
            if name not in self.parameters
        ]
        for name, bound in self.parameters.items():
            if name not in values:
                found.append(f"{name} is required by {self.identity}")
                continue
            value, kind = values[name], bound.get("kind")
            if kind == "integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    found.append(f"{name} must be an integer")
                elif not bound["minimum"] <= value <= bound["maximum"]:
                    found.append(
                        f"{name} must be between {bound['minimum']} and {bound['maximum']}"
                    )
            elif kind == "choice":
                if value not in bound["choices"]:
                    found.append(f"{name} must be one of {', '.join(bound['choices'])}")
            elif kind == "toggle":
                if not isinstance(value, bool):
                    found.append(f"{name} must be true or false")
            else:
                found.append(f"{name} has a kind this client does not know: {kind!r}")
        return found

    def describe(self) -> str:
        parts = []
        for name, bound in self.parameters.items():
            kind = bound.get("kind")
            if kind == "integer":
                span = f"{bound['minimum']}..{bound['maximum']}"
            elif kind == "choice":
                span = "|".join(bound["choices"])
            else:
                span = str(kind)
            parts.append(f"{name} {span} (default {bound.get('default')!r})")
        return f"{self.identity}: " + ", ".join(parts)


def reviewed_behaviours(listing: Iterable[Mapping[str, Any]]) -> list[Behaviour]:
    """The server's behaviour registry, as this client reads it."""
    return [
        Behaviour(row["behaviour_key"], int(row["behaviour_version"]), dict(row["parameters"]))
        for row in listing
    ]


def parse_behaviour_identity(text: str) -> tuple[str, int]:
    """``KEY@VERSION`` as the pair the server keys its registry by."""
    key, separator, version = text.rpartition("@")
    if not separator or not key or not version.isdigit():
        raise ValueError(f"{text!r} is not a behaviour written as KEY@VERSION")
    return key, int(version)
