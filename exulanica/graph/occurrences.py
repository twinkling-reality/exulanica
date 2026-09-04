"""What was detected, and what the system would like to ask about it.

Both are keyed by occurrence, which is why they are one module: a proposal is a question about
an occurrence, and reading one without the other gives an interface a question it cannot show
the evidence for.
"""

from __future__ import annotations

import uuid

import psycopg

from exulanica.graph.payload import OccurrenceRow, ProposalRow

__all__ = ["occurrence_rows", "proposal_rows"]


def occurrence_rows(connection: psycopg.Connection, workspace: uuid.UUID) -> list[OccurrenceRow]:
    """Every occurrence, with the link that names it when one exists.

    ``link_state`` is carried rather than collapsed to a boolean, because ``auto_provisional``
    and ``confirmed`` are different things to the interface: one may drive layout and the other
    may support a claim.
    """
    rows = connection.execute(
        "select o.occurrence_id, o.capture_id, o.class, o.primary_span_id, "
        "  l.entity_id, l.state, c.started_at "
        "from occurrence o "
        "join capture c on c.capture_id = o.capture_id "
        "left join entity_link l on l.occurrence_id = o.occurrence_id "
        "  and l.state = any(array['confirmed','auto_provisional']::link_state[]) "
        "where o.workspace_id = %s and c.deleted_at is null "
        "and not exists (select 1 from entity_link withdrawn "
        "  join entity e on e.entity_id = withdrawn.entity_id "
        "  where withdrawn.workspace_id = o.workspace_id "
        "    and withdrawn.occurrence_id = o.occurrence_id "
        "    and withdrawn.state = 'confirmed' and e.deleted_at is not null) "
        "order by o.occurrence_id",
        (workspace,),
    ).fetchall()
    return [
        OccurrenceRow(
            occurrence_id=row["occurrence_id"],
            capture_id=row["capture_id"],
            occurrence_class=row["class"],
            primary_span_id=row["primary_span_id"],
            entity_id=row["entity_id"],
            link_state=row["state"],
            captured_at=row["started_at"].isoformat() if row["started_at"] else None,
        )
        for row in rows
    ]


def proposal_rows(connection: psycopg.Connection, workspace: uuid.UUID) -> list[ProposalRow]:
    """Candidate matches, including the ones suppressed by a previous rejection.

    Suppressed proposals are returned rather than filtered out, with the flag set. The client
    needs to know not to offer one as though it were fresh, and hiding it entirely would make
    "why is it not asking me about this" unanswerable.

    ``new_modality`` is what this proposal carries that the user has not already refused for the
    pair, and it is what lets an interface say why it is asking again rather than appearing to
    nag. It is NULL when nothing about the pair was refused before, which is the ordinary case
    and not an absent value.

    ``suppressed_by_rejection`` is DERIVED here rather than read off ``outcome``, for the same
    reason ``pending_match_proposal`` exists. ``outcome`` records what the producer decided when
    it wrote the row, and the emit key is deliberately keyed on the question rather than on the
    answer, so a proposal the user rejects afterwards keeps ``outcome = 'surfaced'`` forever: the
    next pass recomputes the same key and ``on conflict do nothing`` declines to rewrite it.
    Reading the column would then show a refused proposal as a live one. Whether it is suppressed
    is a fact about the user's decisions, so it is answered from those.
    """
    rows = connection.execute(
        "select m.proposal_id, m.occurrence_id, m.entity_id, m.rank, m.outcome, m.basis, "
        "  m.new_modality, o.span_ids, "
        # The id-4 subset test, in SQL. A rejection with NULL modalities was spoken unprompted
        # about the user's own photograph and covers every basis; one with a list covers a
        # proposal whose basis is a subset of it.
        "  exists (select 1 from identity_rejection r "
        "           where r.workspace_id = m.workspace_id and r.scope = 'occurrence_entity' "
        "             and r.key_a = o.identity_key and r.key_b = uuid_send(m.entity_id) "
        "             and r.revoked_at is null "
        "             and (r.basis_modalities is null or coalesce(array(select "
        "                   jsonb_array_elements_text(m.basis -> 'modalities')), '{}'::text[]) "
        "                  <@ r.basis_modalities)) as refused "
        "from match_proposal m join occurrence o on o.occurrence_id = m.occurrence_id "
        "join entity proposed on proposed.entity_id = m.entity_id "
        "where m.workspace_id = %s and proposed.deleted_at is null "
        "and not exists (select 1 from entity_link withdrawn "
        "  join entity e on e.entity_id = withdrawn.entity_id "
        "  where withdrawn.workspace_id = o.workspace_id "
        "    and withdrawn.occurrence_id = o.occurrence_id "
        "    and withdrawn.state = 'confirmed' and e.deleted_at is not null) "
        "order by m.occurrence_id, m.rank",
        (workspace,),
    ).fetchall()
    return [
        ProposalRow(
            proposal_id=row["proposal_id"],
            occurrence_id=row["occurrence_id"],
            entity_id=row["entity_id"],
            rank=int(row["rank"]),
            outcome=row["outcome"],
            basis=row["basis"],
            new_modality=row["new_modality"],
            suppressed_by_rejection=bool(row["refused"]),
            support_span_ids=list(row["span_ids"]),
        )
        for row in rows
    ]
