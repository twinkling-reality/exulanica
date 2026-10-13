"""Bounded declared appearance matching of retained inventory identities.

Selection and final authorization are per request. Byte inspection carries no permission, and
results are published only for the same appearance resolved again after all byte reads.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.world.appearance_colour import (
    ColourInterval,
    ColourSwatch,
    colour_facts,
    match_colour,
)
from exulanica.world.errors import InvalidThingPlacement
from exulanica.world.placed_things import ThingKindReference, shipped_kind
from exulanica.world.society_kinds import is_made
from exulanica.world.static_glb import LIMITS, StaticGlbRefused, inspect_static_glb
from exulanica.world.static_glb import PROFILE as STATIC_PROFILE
from exulanica.world.thing_library import thing_library
from exulanica.world.thing_looks import effective_look
from exulanica.world.thing_store import ThingStore

PROFILE = "exulanica.world-entity-query/v1"
MAXIMUM_ENTITIES = 256
MAXIMUM_CONTAINER_BYTES = 32 * 1024 * 1024
MAXIMUM_PRIMITIVES = LIMITS.draw_calls
ReferenceKey = tuple[str, str, str | None]


@dataclass(frozen=True, slots=True)
class Appearance:
    """Exact retained selection, with no claim that it remains authorized later."""

    subject_id: str
    kind_sha256: str
    source: str
    look_sha256: str
    container_sha256: str
    container_bytes: int
    container_profile: str

    def document(self) -> dict[str, str]:
        return {key: getattr(self, key) for key in ("source", "look_sha256", "container_sha256")}


def reference_key(entity: Mapping[str, Any]) -> ReferenceKey:
    ref = entity["reference"]
    return ref["source"], ref["id"], ref.get("role_key")


def resolve_appearances(
    connection: Any,
    workspace_id: uuid.UUID,
    inventory: dict[str, Any],
    *,
    maximum_entities: int = MAXIMUM_ENTITIES,
) -> dict[ReferenceKey, Appearance | str]:
    """Resolve only things-family society records; unsupported authorities remain explicit."""
    result: dict[ReferenceKey, Appearance | str] = {}
    society = inventory["read"].get("society")
    for index, entity in enumerate(inventory["entities"]):
        key = reference_key(entity)
        if index >= maximum_entities:
            result[key] = "entity_budget"
            continue
        record = next(
            (
                source["record"]
                for source in entity["sources"]
                if source["source"] in {"society-being", "society-thing"}
            ),
            None,
        )
        if record is None or society is None or entity.get("detail") is None:
            result[key] = "appearance_adapter_unavailable"
            continue
        if entity["availability"] != "available":
            result[key] = "entity_unavailable"
            continue
        raw = record["kind"]
        workspace_kind = is_made(raw)
        try:
            kind = (
                ThingStore(connection, workspace_id, None).kind_by_digest(raw["sha256"])
                if workspace_kind
                else shipped_kind(ThingKindReference(**raw))
            )
        except InvalidThingPlacement:
            kind = None
        if kind is None:
            result[key] = "kind_unavailable"
            continue
        resolved = effective_look(
            connection,
            workspace_id,
            inventory["world_id"],
            uuid.UUID(inventory["version_id"]),
            str(record["id"]),
            kind,
            workspace_kind=workspace_kind,
        )
        if resolved is None:
            result[key] = "look_unavailable"
            continue
        container = resolved.look.document.get("container")
        if container is None:
            result[key] = "container_unavailable"
            continue
        profile = STATIC_PROFILE
        if resolved.reference.source == "workspace":
            kept = ThingStore(connection, workspace_id, None).look_by_digest(resolved.look.sha256)
            if kept is None:
                result[key] = "look_unavailable"
                continue
            if (
                kept.container_sha256 != container["sha256"]
                or kept.container_bytes != container["bytes"]
            ):
                result[key] = "container_binding_mismatch"
                continue
            profile = kept.container_profile
        result[key] = Appearance(
            str(record["id"]),
            raw["sha256"],
            resolved.reference.source,
            resolved.look.sha256,
            container["sha256"],
            container["bytes"],
            profile,
        )
    return result


def appearance_bytes(appearance: Appearance, services: Any, workspace_id: uuid.UUID) -> bytes:
    """Read an exact retained container from its original scoped authority."""
    if appearance.source == "workspace":
        if services.content_stores is None:
            raise BlobNotFoundError("look store unavailable")
        return services.content_stores.looks.for_workspace(workspace_id).get(
            BlobId.from_hex(appearance.container_sha256)
        )
    item = thing_library().content.get(appearance.container_sha256)
    if item is None:
        raise BlobNotFoundError("look container unavailable")
    return item.data


def inspect_appearances(
    selected: Mapping[ReferenceKey, Appearance | str],
    read_bytes: Callable[[Appearance], bytes],
    *,
    maximum_container_bytes: int = MAXIMUM_CONTAINER_BYTES,
    maximum_primitives: int = MAXIMUM_PRIMITIVES,
) -> dict[ReferenceKey, dict[str, Any] | str]:
    """Load and inspect within shared request budgets; cache only pure facts for exact bytes."""
    result: dict[ReferenceKey, dict[str, Any] | str] = {}
    cache: dict[tuple[str, str, int], dict[str, Any] | str] = {}
    remaining_bytes, remaining_primitives = maximum_container_bytes, maximum_primitives
    for key, appearance in selected.items():
        if isinstance(appearance, str):
            result[key] = appearance
            continue
        cache_key = (
            appearance.container_sha256,
            appearance.container_profile,
            appearance.container_bytes,
        )
        if cache_key in cache:
            result[key] = cache[cache_key]
            continue
        facts: dict[str, Any] | str
        if appearance.container_profile != STATIC_PROFILE:
            facts = "unsupported_profile"
        elif appearance.container_bytes > remaining_bytes:
            facts = "container_byte_budget"
        elif remaining_primitives < 1:
            facts = "primitive_budget"
        else:
            # Reserve declared bytes on failures too, so failed loads cannot evade work bounds.
            remaining_bytes -= appearance.container_bytes
            try:
                data = read_bytes(appearance)
                if (
                    len(data) != appearance.container_bytes
                    or hashlib.sha256(data).hexdigest() != appearance.container_sha256
                ):
                    facts = "container_binding_mismatch"
                else:
                    facts = colour_facts(
                        inspect_static_glb(data),
                        maximum_primitives=min(remaining_primitives, LIMITS.draw_calls),
                    )
                    remaining_primitives -= facts["coverage"]["examined"]
            except (BlobNotFoundError, OSError):
                facts = "container_unavailable"
            except IntegrityError:
                facts = "container_binding_mismatch"
            except StaticGlbRefused:
                facts = "unsupported_container"
        result[key] = cache[cache_key] = facts
    return result


def query_result(
    inventory: dict[str, Any],
    initial: Mapping[ReferenceKey, Appearance | str],
    final: Mapping[ReferenceKey, Appearance | str],
    inspected: Mapping[ReferenceKey, dict[str, Any] | str],
    predicate: ColourSwatch | ColourInterval,
    predicate_document: dict[str, Any],
) -> dict[str, Any]:
    """Publish only final inventory identities with unchanged authorized appearance bindings."""
    entities = []
    counts = {
        "total": len(inventory["entities"]),
        "evaluated": 0,
        "matched": 0,
        "no_match": 0,
        "unknown": 0,
    }
    complete = not inventory["representations"] and all(
        row["state"] in {"complete", "absent"} for row in inventory["coverage"]
    )
    for entity in inventory["entities"]:
        key = reference_key(entity)
        appearance = final[key]
        facts = inspected.get(key, "appearance_changed")
        reason = (
            appearance
            if isinstance(appearance, str)
            else (
                "appearance_changed"
                if appearance != initial.get(key)
                else facts
                if isinstance(facts, str)
                else None
            )
        )
        matched = (
            {
                "state": "unknown",
                "matches": [],
                "coverage": {
                    "state": "unknown",
                    "reason": reason,
                    "total": None,
                    "examined": 0,
                    "known": 0,
                    "unknown": None,
                    "unexamined": None,
                },
            }
            if reason is not None
            else match_colour(facts, predicate)
        )
        if reason is None:
            counts["evaluated"] += 1
        counts["matched" if matched["state"] == "match" else matched["state"]] += 1
        complete = complete and matched["coverage"]["state"] == "complete"
        entities.append(
            {
                "reference": entity["reference"],
                "aliases": entity["aliases"],
                "state": matched["state"],
                "reason": reason,
                "appearance": appearance.document()
                if reason is None and isinstance(appearance, Appearance)
                else None,
                "match_basis": matched["matches"],
                "coverage": matched["coverage"],
            }
        )
    return {
        "profile": PROFILE,
        "world_id": inventory["world_id"],
        "version_id": inventory["version_id"],
        "read": inventory["read"],
        "consistency": "component-pinned",
        "predicate": predicate_document,
        "entities": entities,
        "coverage": {
            "state": "complete" if complete else "incomplete",
            "entities": counts,
            "sources": inventory["coverage"],
            "representations": len(inventory["representations"]),
        },
        "limits": {
            "maximum_entities": MAXIMUM_ENTITIES,
            "maximum_container_bytes": MAXIMUM_CONTAINER_BYTES,
            "maximum_primitives": MAXIMUM_PRIMITIVES,
        },
    }
