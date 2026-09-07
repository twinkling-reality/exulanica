"""The entity half of the snapshot: who is in the library and what is claimed about them.

Split out of the route because eight SQL statements and a ``distinct on`` whose ordering is
load bearing is not what ``orimera/api/__init__.py`` means by "routes validate and delegate;
nothing here decides anything", and because a read model that only has tests through HTTP has no
tests of its own.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Final

import psycopg

from exulanica.graph.payload import AssertionRow, EntityRow, HistoryRow

__all__ = ["NAME_PREDICATE", "entity_rows"]

#: The predicate a naming assertion is written under. Spelled here rather than imported because
#: ``exulanica.identity.naming`` keeps it private, and one duplicated string is cheaper than
#: widening that module's API. ``test_the_graph_reads_the_same_naming_predicate_the_writer_writes``
#: binds the two so they cannot drift, which is the same guard the privacy policy version uses.
NAME_PREDICATE: Final = "name_is"


def _withdrawn_entity_ids(
    connection: psycopg.Connection, workspace: uuid.UUID
) -> frozenset[uuid.UUID]:
    """Entities that are a person who has withdrawn, resolved once for the whole snapshot.

    One query for the workspace rather than a predicate per entity row, deliberately: the person
    layer already cost this package a 44 second test file turning into 3 minutes 28 by asking a
    ``distinct on`` view per photograph (MEASURED 2026-09-06). ``person_subject`` is small, indexed
    on the workspace, and empty in a corpus with no person regions, so the common case is one
    indexed read returning nothing.

    ``person_subject_is_withdrawn`` is called rather than reimplemented, so this agrees with the
    masking rule by construction. It carries no time predicate, unlike ``person_consent_is_granted``
    beside it in migration 0037, so this answer does not change with the clock.
    """
    rows = connection.execute(
        "select distinct s.entity_id from person_subject s "
        "where s.workspace_id = %s and s.entity_id is not null "
        "  and person_subject_is_withdrawn(s.workspace_id, s.subject_id)",
        (workspace,),
    ).fetchall()
    return frozenset(row["entity_id"] for row in rows)


def entity_rows(connection: psycopg.Connection, workspace: uuid.UUID) -> list[EntityRow]:
    """Every live entity, with the captures it is confirmed in and the claims about it.

    Capture ids rather than island ids, because an island is a layout decision the client owns.
    ``open_question_count`` counts proposals still AWAITING AN ANSWER, from
    ``pending_match_proposal``. It cannot count ``outcome = 'surfaced'``: outcome records what
    the producer decided, so counting it would count answered proposals forever and the ambient
    counter would read the same number for the rest of time. The view is the same one
    ``/identity/confirm`` checks against, so the count on screen and the check on the write
    cannot disagree.
    """
    rows = connection.execute(
        "select e.entity_id, e.class, e.display_name, e.merged_into, "
        "  count(distinct l.occurrence_id) as occurrence_count, "
        "  array_remove(array_agg(distinct o.capture_id), null) as capture_ids, "
        "  min(c.started_at) as first_seen, max(c.started_at) as last_seen, "
        "  (select count(*) from pending_match_proposal m "
        "     where m.workspace_id = e.workspace_id and m.entity_id = e.entity_id) "
        "     as open_questions "
        "from entity e "
        "left join entity_link l on l.entity_id = e.entity_id and l.state = 'confirmed' "
        "left join occurrence o on o.occurrence_id = l.occurrence_id "
        "left join capture c on c.capture_id = o.capture_id "
        "where e.workspace_id = %s and e.deleted_at is null "
        "group by e.entity_id, e.class, e.display_name, e.merged_into, e.workspace_id "
        "order by e.entity_id",
        (workspace,),
    ).fetchall()
    # Resolved once and threaded into all three builders, because a withdrawn person's name is
    # carried by three separate fields of this one payload and closing any two of them is not
    # closing the leak. MEASURED 2026-09-07: the region row was blanked first, and the same
    # response still shipped the name in `entities[].display_name` and again inside the rename
    # event's payload. `web/packages/graph-client/src/snapshot.ts` maps both into the client model.
    withdrawn = _withdrawn_entity_ids(connection, workspace)
    assertions = _assertions_by_entity(connection, workspace, withdrawn)
    history = _history_by_entity(connection, workspace, withdrawn)
    return [
        EntityRow(
            entity_id=row["entity_id"],
            entity_class=row["class"],
            # The entity stays in the payload and loses its name. Dropping the row instead would
            # change occurrence counts and break links that point at it, and it would also hide
            # that a decision was made; a withdrawal is meant to be visible as a withdrawal.
            display_name=None if row["entity_id"] in withdrawn else row["display_name"],
            merged_into=row["merged_into"],
            occurrence_count=int(row["occurrence_count"]),
            capture_ids=list(row["capture_ids"]),
            first_seen=row["first_seen"].isoformat() if row["first_seen"] else None,
            last_seen=row["last_seen"].isoformat() if row["last_seen"] else None,
            open_question_count=int(row["open_questions"]),
            assertions=assertions.get(row["entity_id"], []),
            history=history.get(row["entity_id"], []),
            contradictions=[],
        )
        for row in rows
    ]


def _assertions_by_entity(
    connection: psycopg.Connection, workspace: uuid.UUID, withdrawn: frozenset[uuid.UUID]
) -> dict[uuid.UUID, list[AssertionRow]]:
    """Every claim whose subject is an entity, grouped.

    Superseded and retracted rows are included, not filtered. The entity detail view renders
    history and "nothing is ever silently rewritten"; a client that received only the active
    rows could not show that something was withdrawn.

    A withdrawn person's naming assertion is the one exception, and it is a redaction rather than
    a removal: the row stays, so the ledger still shows that somebody was named and when, and its
    ``object_value`` goes to ``None`` so the name itself does not travel. Keeping the row and
    dropping the value is the smaller lie of the two available, and it is the only one that leaves
    both rules standing. Only the naming predicate is touched: whether a withdrawn person's OTHER
    claims should travel is a product question about the ledger, not this defect, and it is
    recorded in docs/person-presentation-consent.md rather than decided here.
    """
    rows = connection.execute(
        "select a.assertion_id, a.kind, p.key, a.status, a.object_value, a.support_span_ids, "
        "  a.produced_by_run, a.stated_by_user, a.external_source, a.asserted_at, a.supersedes, "
        "  a.subject_ref->>'id' as subject_id "
        "from assertion a join predicate p on p.predicate_id = a.predicate_id "
        "where a.workspace_id = %s and a.subject_ref->>'type' = 'entity' "
        "order by a.asserted_at, a.assertion_id",
        (workspace,),
    ).fetchall()
    grouped: dict[uuid.UUID, list[AssertionRow]] = {}
    for row in rows:
        grouped.setdefault(uuid.UUID(row["subject_id"]), []).append(
            AssertionRow(
                assertion_id=row["assertion_id"],
                kind=row["kind"],
                predicate_key=row["key"],
                status=row["status"],
                object_value=(
                    None
                    if row["key"] == NAME_PREDICATE and uuid.UUID(row["subject_id"]) in withdrawn
                    else row["object_value"]
                ),
                support_span_ids=list(row["support_span_ids"]),
                produced_by=_producer(row),
                asserted_at=row["asserted_at"].isoformat(),
                supersedes=row["supersedes"],
            )
        )
    return grouped


def _producer(row: Mapping[str, Any]) -> dict[str, Any]:
    """Which of the four provenance classes made this claim, and the evidence of that.

    Built from the columns the schema constrains rather than from the ``kind`` alone, so a row
    that claimed to be a user statement without naming a human would produce a producer that
    says so instead of one that looks complete.
    """
    if row["kind"] == "user":
        return {"by": "user", "stated_by": str(row["stated_by_user"])}
    if row["kind"] == "inference":
        return {"by": "pipeline", "run_id": str(row["produced_by_run"])}
    if row["kind"] == "external":
        return {"by": "external", "source": row["external_source"]}
    run = row["produced_by_run"]
    return {"by": "capture", "run_id": str(run) if run else None}


def _history_by_entity(
    connection: psycopg.Connection, workspace: uuid.UUID, withdrawn: frozenset[uuid.UUID]
) -> dict[uuid.UUID, list[HistoryRow]]:
    """The identity ledger, grouped by the entity each event names.

    An event's payload carries the ids it touched, and an event can name more than one, so a
    merge appears in the history of every entity involved. That is the honest rendering: a merge
    is one decision and it happened to all of them.

    That sharing is exactly why the name has to be redacted on the EVENT and not on the entity
    whose history it lands in. One event naming both a withdrawn person and somebody else appears
    in both lists, and redacting per list would leave the withdrawn person's name intact in the
    other one. So an event that names any withdrawn entity loses its name key everywhere. That
    over-redacts a merge naming two people of whom one withdrew, and it over-redacts in the
    direction of showing a name that nobody has a receipt for, which is the direction default deny
    chooses every time.

    Only ``exulanica.identity.naming`` writes a name into an event payload today. The walk below
    is written over the payload shape rather than that one event type for the same reason
    ``_entities_named_in`` is: a reader per type is a list somebody has to remember to extend.
    """
    rows = connection.execute(
        "select event_id, type, actor, payload, undoes, created_at from identity_event "
        "where workspace_id = %s order by created_at, event_id",
        (workspace,),
    ).fetchall()
    grouped: dict[uuid.UUID, list[HistoryRow]] = {}
    for row in rows:
        named = _entities_named_in(row["payload"])
        event = HistoryRow(
            event_id=row["event_id"],
            event_type=row["type"],
            actor=row["actor"],
            payload=(_without_names(row["payload"]) if named & withdrawn else row["payload"]),
            undoes=row["undoes"],
            created_at=row["created_at"].isoformat(),
        )
        for entity_id in named:
            grouped.setdefault(entity_id, []).append(event)
    return grouped


def _without_names(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The same payload with every name in it removed, at any depth.

    The key is dropped rather than set to ``None``, so a client rendering "what changed" shows a
    rename event that does not say what the name became, instead of one asserting the name became
    nothing. The event, its actor and its time all survive: the ledger still shows a naming
    happened, which is what makes a withdrawal auditable rather than invisible.
    """

    def strip(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: strip(value) for key, value in node.items() if key != "display_name"}
        if isinstance(node, list):
            return [strip(item) for item in node]
        return node

    return strip(dict(payload))


def _entities_named_in(payload: Mapping[str, Any]) -> set[uuid.UUID]:
    """Every entity id anywhere in an event payload, whatever shape that payload has.

    A walk rather than a per-type reader, because the payloads differ by event type and a reader
    per type is a list somebody has to remember to extend. A value that is not a uuid is not an
    entity id and is skipped.
    """
    found: set[uuid.UUID] = set()
    stack: list[Any] = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.values())
            stack.extend(node.keys())
        elif isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, str):
            try:
                found.add(uuid.UUID(node))
            except ValueError:
                continue
    return found
