"""One user decision, applied as one transaction, recorded so that undo is exact.

Five decisions live here: confirm, reject, revoke, merge and split, plus the naming of an
occurrence. Their shared vocabulary is in :mod:`exulanica.identity.subjects`, their inverses are in
:mod:`exulanica.identity.undo`, and renaming an entity is in :mod:`exulanica.identity.naming`. The
split happened when this file passed 700 lines and was holding three responsibilities at once.

Every function here is a thing a person did. There is no function a model can call, and that is
structural rather than a matter of discipline: ``confirmed_needs_a_human`` refuses a confirmed
link without a ``decided_by`` and ``method = 'user_confirm'``, and
``tg_entity_name_is_user_stated`` refuses a name that no active ``kind='user'`` assertion
supports. A caller that wanted to promote a guess would have to defeat the database.

**A name is not stored, it is derived.** :func:`name_occurrence` writes the naming assertion
first and sets ``entity.display_name`` second, and the second write succeeds only because the
first one exists. Retracting the assertion clears the column. The column is a cache of the
claim, never the claim itself, which is what makes "the user changed their mind" a single write
rather than a cleanup job.

**Rejection memory is keyed by evidence and by basis.** A rejection says "not this occurrence,
not this entity, not on this evidence". Keyed by ``occurrence_id`` instead, the next detector
run mints a new id for the same thing in the same photograph and the rejected proposal comes
straight back forever. Keyed without the basis, a genuinely better signal set could never ask
again, which is the opposite failure and just as bad.

**What is deliberately absent.** No function here computes, stores or compares an embedding of
any kind. Identity is established by the account holder pointing at a photograph and saying who
that is. Automatic proposal from non-biometric signals (time proximity, scene grouping, place,
co-occurrence) writes ``match_proposal`` rows and organizational guesses through
:meth:`exulanica.identity.proposals.Proposals.record`; face embeddings are a separate decision with
legal weight and open item P-1 has not been answered.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity.keys import USER_STATEMENT_BASIS
from exulanica.identity.repository import IdentityRepository
from exulanica.identity.subjects import (
    ENTITY_ENTITY,
    OCCURRENCE_ENTITY,
    AlreadyIdentified,
    IdentityError,
    NamedPerson,
    NeverSame,
    UnknownSubject,
    require_entity,
    require_occurrence,
)

#: Re-exported so that `from exulanica.identity.decisions import OCCURRENCE_ENTITY` keeps working
#: and so the two rejection scopes stay readable beside the decisions that file them.
__all__ = [
    "ENTITY_ENTITY",
    "OCCURRENCE_ENTITY",
    "confirm_link",
    "merge_entities",
    "name_occurrence",
    "reject_link",
    "revoke_link",
    "split_entity",
]

#: The only method a confirmed link may carry, per ``confirmed_needs_a_human``.
_USER_CONFIRM = "user_confirm"

def name_occurrence(
    repository: IdentityRepository,
    assertions: AssertionWriter,
    *,
    occurrence_id: uuid.UUID,
    display_name: str,
    actor: uuid.UUID,
) -> NamedPerson:
    """The account holder points at somebody in a photograph and says who that is.

    This is the whole of rung one, and it is the version that needs no biometric decision: a
    person is identified because a person said so. Four rows in one transaction, in an order
    that is not interchangeable:

    1. An entity, unnamed. There is no argument for a name on ``entities.create``.
    2. A ``kind='user'`` assertion under ``name_is``, citing the occurrence's own evidence span
       and naming ``actor`` as the person who said it.
    3. ``entity.display_name``, which the trigger permits only because step 2 exists.
    4. A confirmed link from the occurrence to the entity.

    Reverse steps 2 and 3 and the database refuses the update, which is the point: there is no
    ordering of these writes in which a name lands without a statement behind it.
    """
    display_name = display_name.strip()
    if not display_name:
        raise IdentityError("a name is a thing somebody said; the empty string is not one")

    occurrence = require_occurrence(repository, occurrence_id)
    existing = repository.links.for_occurrence(occurrence_id)
    if existing is not None:
        raise AlreadyIdentified(
            f"occurrence {occurrence_id} is already confirmed as entity {existing.entity_id}. "
            "Naming it again would create a second identity for one person in one photograph; "
            "rename that entity, or revoke the link first."
        )

    with repository.transaction():
        entity_id = repository.entities.create(entity_class=occurrence.occurrence_class)
        assertion_id = assertions.insert(
            kind="user",
            predicate_key="name_is",
            subject_ref={"type": "entity", "id": str(entity_id)},
            object_value=display_name,
            # The span the user was looking at when they said it. A user statement needs no
            # support under the schema, but a naming that cites the photograph it was made from
            # is a better record than one that cites nothing.
            support_span_ids=[occurrence.primary_span_id],
            stated_by_user=actor,
            emit_key=f"identity:name:{entity_id}",
        )
        assert assertion_id is not None, "a fresh entity id cannot collide on emit_key"
        repository.entities.set_name_cache(entity_id, display_name)
        link_id = repository.links.insert(
            occurrence_id=occurrence_id,
            entity_id=entity_id,
            state="confirmed",
            method=_USER_CONFIRM,
            basis_digest=USER_STATEMENT_BASIS,
            decided_by=actor,
        )
        created = repository.events.record(
            "entity_created",
            actor=actor,
            payload={
                "entity_id": str(entity_id),
                "class": occurrence.occurrence_class,
                "named_from_occurrence": str(occurrence_id),
                "assertion_id": str(assertion_id),
            },
        )
        confirmed = repository.events.record(
            "link_confirmed",
            actor=actor,
            payload={
                "link_id": str(link_id),
                "occurrence_id": str(occurrence_id),
                "entity_id": str(entity_id),
                "method": _USER_CONFIRM,
            },
        )
        repository.recomputation.mark_stale(entity=entity_id, occurrence=occurrence_id)
    return NamedPerson(
        entity_id=entity_id,
        link_id=link_id,
        assertion_id=assertion_id,
        event_ids=(created, confirmed),
    )


def confirm_link(
    repository: IdentityRepository,
    *,
    occurrence_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor: uuid.UUID,
) -> uuid.UUID:
    """The account holder says this occurrence is that person. The recurrence thesis, once.

    A previous rejection of this exact pairing is revoked rather than honoured. Rejection memory
    exists to stop the SYSTEM re-proposing something the user already refused; the user refusing
    and then changing their mind is not a re-proposal, and a memory that overruled them would be
    the product arguing with its owner about their own life.
    """
    occurrence = require_occurrence(repository, occurrence_id)
    entity = require_entity(repository, entity_id)
    target = repository.entities.resolve(entity.entity_id)

    existing = repository.links.for_occurrence(occurrence_id)
    if existing is not None:
        if repository.entities.resolve(existing.entity_id) == target:
            return existing.link_id
        raise AlreadyIdentified(
            f"occurrence {occurrence_id} is already confirmed as entity {existing.entity_id}, "
            f"not {target}. Revoke that link before confirming a different person."
        )

    with repository.transaction():
        # Every live no about this pair, not only the one the user themselves said. Confirming
        # is a change of mind about the PAIR, and a machine rejection left live would suppress
        # future proposals for a link the account holder has now confirmed. The ids are recorded
        # on the event so undo restores exactly these and not whatever is live at the time.
        revoked = repository.rejections.revoke_all(
            scope=OCCURRENCE_ENTITY,
            key_a=occurrence.identity_key,
            key_b=target.bytes,
        )
        proposed = repository.links.for_occurrence(
            occurrence_id, states=("proposed", "auto_provisional")
        )
        if proposed is not None:
            repository.links.set_state(proposed.link_id, "revoked")
        link_id = repository.links.insert(
            occurrence_id=occurrence_id,
            entity_id=target,
            state="confirmed",
            method=_USER_CONFIRM,
            basis_digest=USER_STATEMENT_BASIS,
            decided_by=actor,
        )
        repository.events.record(
            "link_confirmed",
            actor=actor,
            payload={
                "link_id": str(link_id),
                "occurrence_id": str(occurrence_id),
                "entity_id": str(target),
                "method": _USER_CONFIRM,
                "superseded_proposal": str(proposed.link_id) if proposed else None,
                "revoked_rejections": [str(value) for value in revoked],
            },
        )
        repository.recomputation.mark_stale(entity=target, occurrence=occurrence_id)
    return link_id


def reject_link(
    repository: IdentityRepository,
    *,
    occurrence_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor: uuid.UUID,
    basis_digest: bytes = USER_STATEMENT_BASIS,
    basis_modalities: Sequence[str] | None = None,
) -> uuid.UUID:
    """No, that is not them. Remembered against the evidence, not against the row.

    ``basis_digest`` defaults to the user's own statement. A caller rejecting a proposal should
    pass the proposal's basis instead, so that a later proposal built from genuinely different
    signals is not silently suppressed by an answer to a different question.

    ``basis_modalities`` is what the user was SHOWN, and None means nothing: they looked at their
    own photograph and said no, unprompted. That suppresses every later proposal for the pair,
    because no machine signal outranks a person about their own life. Passing an empty list would
    suppress nothing at all and is refused by the database. The digest alone cannot carry this,
    because it covers extractor versions, so a version bump would move it and revive every
    rejection.
    """
    occurrence = require_occurrence(repository, occurrence_id)
    entity = require_entity(repository, entity_id)
    target = repository.entities.resolve(entity.entity_id)

    confirmed = repository.links.for_occurrence(occurrence_id)
    if confirmed is not None and repository.entities.resolve(confirmed.entity_id) == target:
        raise AlreadyIdentified(
            f"occurrence {occurrence_id} is confirmed as entity {target}. Rejecting a confirmed "
            "link is a withdrawal of something the user already said: use revoke_link."
        )

    with repository.transaction():
        proposed = repository.links.for_occurrence(
            occurrence_id, states=("proposed", "auto_provisional")
        )
        if proposed is not None and repository.entities.resolve(proposed.entity_id) == target:
            repository.links.set_state(proposed.link_id, "rejected")
        rejection_id = repository.rejections.record(
            scope=OCCURRENCE_ENTITY,
            key_a=occurrence.identity_key,
            key_b=target.bytes,
            basis_digest=basis_digest,
            rejected_by=actor,
            basis_modalities=basis_modalities,
        )
        repository.events.record(
            "link_rejected",
            actor=actor,
            payload={
                "rejection_id": str(rejection_id),
                "occurrence_id": str(occurrence_id),
                "entity_id": str(target),
                "identity_key": occurrence.identity_key.hex(),
                "basis_digest": basis_digest.hex(),
                "basis_modalities": list(basis_modalities) if basis_modalities else None,
                "link_id": str(proposed.link_id) if proposed else None,
            },
        )
        repository.recomputation.mark_stale(entity=target, occurrence=occurrence_id)
    return rejection_id


def revoke_link(
    repository: IdentityRepository,
    *,
    occurrence_id: uuid.UUID,
    actor: uuid.UUID,
    remember: bool = True,
) -> uuid.UUID:
    """Withdraw a confirmed link. The user was wrong, or has changed their mind.

    ``remember`` writes rejection memory as well, which is usually right: having said "that is
    not Julie after all", being asked again about the same photograph is the product not
    listening. Pass False when the revocation is bookkeeping rather than a judgement, as it is
    inside :func:`split_entity`.
    """
    occurrence = require_occurrence(repository, occurrence_id)
    link = repository.links.for_occurrence(occurrence_id)
    if link is None:
        raise UnknownSubject(f"occurrence {occurrence_id} has no confirmed link to revoke")

    with repository.transaction():
        repository.links.set_state(link.link_id, "revoked")
        if remember:
            repository.rejections.record(
                scope=OCCURRENCE_ENTITY,
                key_a=occurrence.identity_key,
                key_b=link.entity_id.bytes,
                basis_digest=USER_STATEMENT_BASIS,
                rejected_by=actor,
            )
        event_id = repository.events.record(
            "link_revoked",
            actor=actor,
            payload={
                "link_id": str(link.link_id),
                "occurrence_id": str(occurrence_id),
                "entity_id": str(link.entity_id),
                "remembered": remember,
            },
        )
        repository.recomputation.mark_stale(
            entity=link.entity_id, occurrence=occurrence_id
        )
    return event_id


def merge_entities(
    repository: IdentityRepository,
    *,
    sources: list[uuid.UUID],
    target: uuid.UUID,
    actor: uuid.UUID,
) -> uuid.UUID:
    """Two records of one person become one, without rewriting a single link.

    ``entity.merged_into`` is an alias redirect, so every link written before the merge still
    names the entity it was written against and still resolves. That is what makes undo a matter
    of clearing one column rather than replaying a link rewrite, and it is why the event payload
    records the exact link set: an undo that guessed which links belonged to which source would
    be approximate, and approximate is not a property this system offers about identity.
    """
    if target in sources:
        raise IdentityError("an entity cannot be merged into itself")
    surviving = require_entity(repository, target)
    for source in sources:
        absorbed = require_entity(repository, source)
        # THE SURVIVING RECORD KEEPS ITS NAME, so merging a named record into an unnamed one
        # would leave the survivor unnamed and the name readable only in history. A user who
        # wanted that wanted the merge the other way round.
        #
        # Refused here as well as in the client draft, and the duplication is deliberate: the
        # client refusal does not cover a caller that never went through `draftMerge`, and this
        # is the stronger guarantee. A merge that went the wrong way is undoable only if somebody
        # notices, and nothing about an unnamed survivor is loud.
        if surviving.display_name is None and absorbed.display_name is not None:
            raise IdentityError(
                f"merging {absorbed.display_name!r} into a record with no name would leave the "
                "surviving record unnamed. Merge the other way round, so the name somebody "
                "chose is the one that remains."
            )
        if repository.never_same.holds(source, target):
            raise NeverSame(
                f"entities {source} and {target} were split apart by a user decision. "
                "Merging them would silently reverse it; undo the split instead."
            )

    resolved_target = repository.entities.resolve(target)
    payload_links = {
        str(source): [str(link.link_id) for link in repository.links.of_entity(source)]
        for source in sources
    }
    with repository.transaction():
        for source in sources:
            repository.entities.set_merged_into(source, resolved_target)
        event_id = repository.events.record(
            "entities_merged",
            actor=actor,
            payload={
                "from": [str(source) for source in sources],
                "into": str(resolved_target),
                "links": payload_links,
            },
        )
        repository.recomputation.mark_stale(entity=[*sources, resolved_target])
    return event_id


def split_entity(
    repository: IdentityRepository,
    *,
    entity_id: uuid.UUID,
    occurrence_ids: list[uuid.UUID],
    actor: uuid.UUID,
) -> uuid.UUID:
    """These occurrences are somebody else. Moves them to a new, unnamed entity.

    The new entity is unnamed on purpose. The user has said "not that person"; they have not yet
    said who this is, and inventing a name or copying the old one would be the system asserting
    something nobody told it. A ``never_same`` row records the split, so a later merge of the two
    is refused rather than quietly undoing a decision.

    The old link is revoked and a new confirmed one written, rather than the old one being
    repointed. ``entity_link`` is where a decision is recorded; editing one to say something the
    user never said would lose the fact that they once said the other thing.
    """
    if not occurrence_ids:
        raise IdentityError("a split with no occurrences moves nothing")
    require_entity(repository, entity_id)

    links = {link.occurrence_id: link for link in repository.links.of_entity(entity_id)}
    missing = [str(o) for o in occurrence_ids if o not in links]
    if missing:
        raise UnknownSubject(
            f"occurrences {missing} are not confirmed as entity {entity_id}, so a split cannot "
            "move them"
        )
    if len(occurrence_ids) == len(links):
        raise IdentityError(
            "a split that moves every occurrence leaves the original entity empty; that is a "
            "rename, not a split"
        )

    entity = repository.entities.by_id(entity_id)
    assert entity is not None
    with repository.transaction():
        new_entity_id = repository.entities.create(entity_class=entity.entity_class)
        moved: list[dict[str, str]] = []
        for occurrence_id in occurrence_ids:
            old = links[occurrence_id]
            repository.links.set_state(old.link_id, "revoked")
            link_id = repository.links.insert(
                occurrence_id=occurrence_id,
                entity_id=new_entity_id,
                state="confirmed",
                method=_USER_CONFIRM,
                basis_digest=USER_STATEMENT_BASIS,
                decided_by=actor,
            )
            moved.append(
                {
                    "occurrence_id": str(occurrence_id),
                    "revoked_link_id": str(old.link_id),
                    "link_id": str(link_id),
                }
            )
        event_id = repository.events.record(
            "entity_split",
            actor=actor,
            payload={
                "entity_id": str(entity_id),
                "into": str(new_entity_id),
                "moved": moved,
                "kept": [
                    str(occurrence_id)
                    for occurrence_id in links
                    if occurrence_id not in set(occurrence_ids)
                ],
            },
        )
        repository.never_same.record(entity_id, new_entity_id, created_by_event=event_id)
        repository.recomputation.mark_stale(
            entity=[entity_id, new_entity_id], occurrence=occurrence_ids
        )
    return event_id
