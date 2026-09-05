"""A canonical confirmed-exemplar index, consumed by the contextual match proposer.

Identity decisions invalidate this index through its entity and occurrence dependencies. A
refresh rebuilds it from live confirmed evidence; it never clears a historical row's stale bit.
The payload and dependency set, rather than timestamps or refresh history, are deterministic.
"""

from __future__ import annotations

import uuid
from typing import Any

from psycopg.types.json import Jsonb

from exulanica.canonical import sha256_of_canonical
from exulanica.identity.repository import IdentityRepository

__all__ = ["MATCH_CONTEXT_KIND", "refresh_match_context"]

MATCH_CONTEXT_KIND = "identity_match_context"


def refresh_match_context(repository: IdentityRepository) -> dict[str, Any]:
    """Return the persisted, current exemplar index; refuse a stale-on-arrival derivative.

    The canonical payload has no score, model output or clock. Each anchor identifies the
    occurrence, its source entity and its resolved entity, so merges preserve exemplars and
    invalidate through either identity. Capture/interval/entity withdrawals are excluded before
    writing, and the database independently applies its forward-withdrawal guard.
    """
    with repository.transaction():
        return _refresh_match_context(repository)


def _refresh_match_context(repository: IdentityRepository) -> dict[str, Any]:
    rows = repository.connection.execute(
        "select e.entity_id as source_entity_id, o.occurrence_id, o.capture_id, "
        "o.class, o.quality from entity e "
        "join entity_link l on l.workspace_id = e.workspace_id "
        "  and l.entity_id = e.entity_id and l.state = 'confirmed' "
        "join occurrence o on o.workspace_id = l.workspace_id "
        "  and o.occurrence_id = l.occurrence_id "
        "join capture c on c.workspace_id = o.workspace_id and c.capture_id = o.capture_id "
        "where e.workspace_id = %s and e.deleted_at is null and c.deleted_at is null "
        "and not tombstone_blocks_any_span(o.workspace_id, o.span_ids) "
        "and not exists (select 1 from entity_link withdrawn "
        "  join entity w on w.workspace_id = withdrawn.workspace_id "
        "    and w.entity_id = withdrawn.entity_id "
        "  join occurrence wo on wo.occurrence_id = withdrawn.occurrence_id "
        "  where withdrawn.workspace_id = o.workspace_id and wo.capture_id = o.capture_id "
        "    and withdrawn.state = 'confirmed' and w.deleted_at is not null) "
        "order by e.entity_id, o.occurrence_id",
        (repository.workspace_id,),
    ).fetchall()
    anchors = []
    dependencies: set[str] = set()
    sources: set[uuid.UUID] = set()
    for row in rows:
        target = repository.entities.by_id(repository.entities.resolve(row["source_entity_id"]))
        if target is None or target.deleted_at is not None:
            continue
        anchors.append({
            "entity_id": str(target.entity_id),
            "source_entity_id": str(row["source_entity_id"]),
            "occurrence_id": str(row["occurrence_id"]),
            "capture_id": str(row["capture_id"]),
            "display_name": target.display_name,
            "class": row["class"],
            "label": (row["quality"] or {}).get("label"),
        })
        dependencies.update((
            f"entity:{target.entity_id}", f"entity:{row['source_entity_id']}",
            f"occurrence:{row['occurrence_id']}", f"capture:{row['capture_id']}",
        ))
        sources.add(row["capture_id"])
    anchors.sort(key=lambda a: (a["entity_id"], a["occurrence_id"]))
    payload = {"profile": "exulanica.identity-match-context/v1", "anchors": anchors}
    digest = sha256_of_canonical(payload).hex()
    base_id = uuid.uuid5(repository.workspace_id, f"{MATCH_CONTEXT_KIND}:{digest}")
    derived_id = base_id
    generation = 0
    with repository.transaction():
        while True:
            existing = repository.connection.execute(
                "select payload, stale from derived_artifact "
                "where workspace_id = %s and derived_id = %s",
                (repository.workspace_id, derived_id),
            ).fetchone()
            if existing is None or not existing["stale"]:
                break
            generation += 1
            derived_id = uuid.uuid5(base_id, str(generation))
        repository.connection.execute(
            "update derived_artifact set stale = true where workspace_id = %s "
            "and kind = %s and derived_id <> %s and not stale",
            (repository.workspace_id, MATCH_CONTEXT_KIND, derived_id),
        )
        if existing is None:
            repository.connection.execute(
                "insert into derived_artifact "
                "(derived_id, workspace_id, kind, depends_on, dep_index, source_ids, payload) "
                "values (%s, %s, %s, %s, %s::text[], %s::uuid[], %s)",
                (derived_id, repository.workspace_id, MATCH_CONTEXT_KIND,
                 Jsonb([dict(zip(("kind", "id"), dep.split(":", 1), strict=True))
                        for dep in sorted(dependencies)]),
                 sorted(dependencies), sorted(sources), Jsonb(payload)),
            )
        current = repository.connection.execute(
            "select payload from derived_artifact where workspace_id = %s "
            "and derived_id = %s and not stale",
            (repository.workspace_id, derived_id),
        ).fetchone()
        if current is None:
            raise RuntimeError("identity match context was withdrawn during refresh")
        return current["payload"]
