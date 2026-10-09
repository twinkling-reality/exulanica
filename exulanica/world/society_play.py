"""A person playing one being of a society of things ("Play this one"): what they answer, and how.

A person who plays a being chooses, once a minute, among the options its decider is offered, as a
model or an outside program does: the play route serves the options of the minute to come, read from
the society's stored state, and the person posts an answer for that minute, ``{base_tick, label,
line}``. Each answer is kept (``world_society_person_answer``, migration "a person plays one
being"), the latest for a being and a minute taken when the minute comes: the host reserves the
being's request as for any decider and records the person's answer as its receipt, or, where they
posted none, the request's idle option (carrying on, else waiting), ``person_no_answer``, never the
routine and never a model. A being whose person posted nothing for :data:`QUIET_MINUTES` minutes
in a row is given back, ``player_left``.

An answer is checked when it is posted as every decider's is: a label the minute offers, a line
exactly where the option says something, held to the line rule, and no name the account holder saved
in the line (``line_refused_by_rules``), checked again when the minute takes it. An answer names no
account in its document; its row names the account that posted it, which no read shows.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.world.society_engines import society_engine

if TYPE_CHECKING:
    from exulanica.epistemics.saved_names import SavedName
    from exulanica.world.decision_roles import DecisionContract, DecisionRole
    from exulanica.world.society_decision_repository import SocietyDecisionRepository
    from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
    from exulanica.world.society_repository import SocietyRepository

__all__ = [
    "ANSWERS_PER_MINUTE",
    "PERSON_ANSWER_PROFILE",
    "PLAY_REFUSALS",
    "QUIET_MINUTES",
    "PlayRefused",
    "answer_document",
    "answer_played",
    "latest_answer",
    "person_result",
    "quiet_minutes",
    "record_answer",
]

_LOG = logging.getLogger(__name__)

PERSON_ANSWER_PROFILE: Final = "exulanica.person-answer/v1"
#: How many answers one person may post for the being they play in one minute; the latest counts.
ANSWERS_PER_MINUTE: Final = 12
#: How many minutes in a row a played being carries on with no answer from its person before the
#: host gives it back (``player_left``).
QUIET_MINUTES: Final = 5
#: Why an answer is refused, by the code the route answers with, its detail and its status.
PLAY_REFUSALS: Final = {
    "minute_passed": (
        "the minute this answer is for has already been played; read the turn again",
        409,
    ),
    "label_not_offered": ("the being is not offered that this minute", 422),
    "line_needed": ("that option says something: give the line", 422),
    "line_not_taken": ("that option says nothing: give no line", 422),
    "line_out_of_bounds": ("the line breaks the line rule", 422),
    "line_refused_by_rules": ("the line carries a name this workspace keeps", 422),
    "too_many_answers": ("too many answers for this minute; the latest one counts", 429),
}


class PlayRefused(ValueError):
    """An answer the play route refuses, by a code a caller can act on."""

    def __init__(self, code: str, *, tick: int | None = None) -> None:
        detail, status = PLAY_REFUSALS[code]
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status
        #: The society's current minute, where the answer came for another.
        self.tick = tick


def answer_document(subject_id: str, base_tick: int, label: str, line: str | None) -> dict:
    """What an answer states: the being, the minute, the option's label and its line, if any."""
    document: dict[str, Any] = {
        "profile": PERSON_ANSWER_PROFILE,
        "subject_id": subject_id,
        "base_tick": base_tick,
        "label": label,
    }
    if line is not None:
        document["line"] = line
    return document


def _digest(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(document)).hexdigest()


def record_answer(
    connection: psycopg.Connection,
    *,
    workspace_id: uuid.UUID,
    world_id: str,
    society_id: uuid.UUID,
    account_id: uuid.UUID,
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep ``document``, an answer checked by its route, as the latest for its being and minute.
    Refused ``too_many_answers`` past :data:`ANSWERS_PER_MINUTE` from one account."""
    subject_id = uuid.UUID(document["subject_id"])
    base_tick = int(document["base_tick"])
    with connection.transaction():
        connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s, 175001))", (str(subject_id),)
        )
        held = connection.execute(
            "select coalesce(max(answer_seq), 0) as latest, "
            "count(*) filter (where account_id = %(a)s) as mine "
            "from world_society_person_answer where workspace_id = %(w)s and world_id = %(world)s "
            "and society_id = %(s)s and subject_id = %(subject)s and base_tick = %(t)s",
            {
                "a": account_id,
                "w": workspace_id,
                "world": world_id,
                "s": society_id,
                "subject": subject_id,
                "t": base_tick,
            },
        ).fetchone()
        if held["mine"] >= ANSWERS_PER_MINUTE:
            raise PlayRefused("too_many_answers")
        sequence = held["latest"] + 1
        connection.execute(
            "insert into world_society_person_answer (workspace_id, world_id, society_id, "
            "subject_id, base_tick, answer_seq, account_id, document, document_sha256) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                workspace_id,
                world_id,
                society_id,
                subject_id,
                base_tick,
                sequence,
                account_id,
                Jsonb(dict(document)),
                _digest(document),
            ),
        )
    return {**document, "answer_seq": sequence}


def latest_answer(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    society_id: uuid.UUID,
    subject_id: str,
    base_tick: int,
    *,
    account_id: uuid.UUID,
) -> dict[str, Any] | None:
    """The latest answer ``account_id`` posted for ``subject_id`` and the minute ``base_tick``, or
    None: another person's answer for that minute, one who gave the being back before this person
    took it, is never this person's."""
    row = connection.execute(
        "select document from world_society_person_answer where workspace_id = %s "
        "and world_id = %s and society_id = %s and subject_id = %s and base_tick = %s "
        "and account_id = %s order by answer_seq desc limit 1",
        (workspace_id, world_id, society_id, uuid.UUID(subject_id), base_tick, account_id),
    ).fetchone()
    return None if row is None else dict(row["document"])


def answer_played(
    connection: psycopg.Connection,
    society: SocietyRepository,
    *,
    version_id: uuid.UUID,
    actor: uuid.UUID | None = None,
) -> bool:
    """Answer, for the coming minute, every present being a person plays in ``version_id``'s
    society: its request reserved as any decider's, and its receipt the latest answer its person
    posted for this minute, else its idle option (``person_no_answer``); a line carrying a name
    saved since it was posted is not said. A being whose person posted nothing for
    :data:`QUIET_MINUTES` minutes in a row is given back (``player_left``), by ``actor``, or with
    none by that person.

    Nobody is asked and nothing is spent, so the decision host answers played beings before it
    asks any model and wherever it asks none, and every minute stepped answers them before it
    advances, whichever way it is stepped
    (:meth:`~exulanica.world.society_repository.SocietyRepository.advance`): a played being is
    never decided by its routine. A being whose request for the minute is already reserved is left
    as it is. True when a present being is played, so the coming minute runs alone. One being's
    failure costs it alone, and undoes only its own answer."""
    from exulanica.epistemics.saved_names import saved_names
    from exulanica.world.deciders import is_played
    from exulanica.world.decision_roles import decision_roles
    from exulanica.world.society_decision_repository import SocietyDecisionRepository
    from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository

    row = society._row(version_id)
    if row is None or society_engine(str(row["engine_version"])).state_family != "things":
        # Only a society of things' beings are played.
        return False
    choices = SocietyModelChoiceRepository(
        connection, society.workspace_id, world_id=society.world_id
    )
    decisions = SocietyDecisionRepository(society)
    any_played = False
    for role in decision_roles().hosted_by(row["engine_version"]):
        contract = role.contract(role.terms(row["engine_version"]).versions)
        present = set(role.adapter.subjects(row["state"]))
        played = {
            subject: choice
            for subject, choice in choices.deciding(version_id, role, contract).items()
            if is_played(choice["decider"]) and subject in present
        }
        if not played:
            continue
        any_played = True
        names = saved_names(connection, society.workspace_id)
        for subject in sorted(played):
            try:
                with connection.transaction():
                    _answer_one(
                        connection,
                        society,
                        decisions,
                        choices,
                        row,
                        role,
                        contract,
                        subject,
                        played[subject],
                        names,
                        version_id=version_id,
                        actor=actor,
                    )
            except Exception as exc:
                _LOG.error("A played being's answer failed with %s", type(exc).__name__)
    return any_played


def _answer_one(
    connection: psycopg.Connection,
    society: SocietyRepository,
    decisions: SocietyDecisionRepository,
    choices: SocietyModelChoiceRepository,
    row: Mapping[str, Any],
    role: DecisionRole,
    contract: DecisionContract,
    subject: str,
    choice: Mapping[str, Any],
    names: Sequence[SavedName],
    *,
    version_id: uuid.UUID,
    actor: uuid.UUID | None,
) -> None:
    """One played being's answer for the coming minute, and its give-back after its person's
    quiet minutes (:func:`answer_played`)."""
    from exulanica.epistemics.saved_names import recognised_spans
    from exulanica.world.society import asked_again_after_a_race
    from exulanica.world.society_model_choice_repository import ModelChoiceRefused

    tick = row["current_tick"]
    account = uuid.UUID(choice["decider"]["account_id"])
    line_kinds = tuple(getattr(role.adapter, "LINE_KINDS", ()))

    def answer(_last_try: bool) -> dict[str, Any] | None:
        with connection.transaction():
            reserved, fresh = decisions.prepare_role(
                role,
                version_id,
                request_id=uuid.uuid5(
                    row["society_id"], f"{role.subject}-decision:{subject}:{tick}"
                ),
                subject_id=uuid.UUID(subject),
                base_tick=tick,
                base_state_sha256=row["state_sha256"],
                contract=contract,
                provider_config={"kind": "person", "contract": contract.binding()},
            )
            request = reserved["request"]
            if not fresh or request is None:
                return None
            posted = latest_answer(
                connection,
                society.workspace_id,
                society.world_id,
                row["society_id"],
                subject,
                tick,
                account_id=account,
            )
            if posted is not None and recognised_spans(posted.get("line") or "", names):
                posted = None
            result = person_result(
                request["context"],
                role.idle_label(request["context"]),
                posted,
                line_kinds=line_kinds,
            )
            if result is None:
                return None
            decisions.finish(version_id, uuid.UUID(request["request_id"]), result)
            return result

    result = asked_again_after_a_race(answer)
    if result is None or result["reason"] != "person_no_answer":
        return
    quiet = quiet_minutes(
        connection,
        society.workspace_id,
        row["society_id"],
        subject,
        role.receipt_profile,
        int(choice.get("since_tick") or 0),
    )
    if quiet < QUIET_MINUTES:
        return
    try:
        choices.give_back(
            version_id,
            role,
            request_id=uuid.uuid5(row["society_id"], f"player_left:{subject}:{tick}"),
            subject=subject,
            account_id=account,
            chosen_by=account if actor is None else actor,
            contract=contract,
            ended="player_left",
        )
    except ModelChoiceRefused:
        # Given back or played again meanwhile.
        return


def person_result(
    context: Mapping[str, Any],
    idle_label: str | None,
    answer: Mapping[str, Any] | None,
    *,
    line_kinds: Sequence[str],
) -> dict[str, Any] | None:
    """The receipt a played being's request takes: the person's ``answer`` where the request offers
    its label, else the idle option (``person_no_answer``); None where the request offers no idle
    option either, which no request of a played being's role does."""
    options = context["options"]
    if answer is not None:
        option = next((held for held in options if held["label"] == answer["label"]), None)
        takes_line = option is not None and option.get("kind") in line_kinds
        if option is not None and takes_line == ("line" in answer):
            proposal: dict[str, Any] = {"label": option["label"], "option": dict(option)}
            if takes_line:
                proposal["line"] = answer["line"]
            return {
                "status": "accepted",
                "reason": "validated_choice",
                "proposal": proposal,
                "provider": {"kind": "person", "answer_sha256": _digest(answer)},
            }
    idle = next((held for held in options if held["label"] == idle_label), None)
    if idle is None:
        return None
    return {
        "status": "accepted",
        "reason": "person_no_answer",
        "proposal": {"label": idle["label"], "option": dict(idle)},
        "provider": {"kind": "person", "answer_sha256": None},
    }


def quiet_minutes(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    society_id: uuid.UUID,
    subject_id: str,
    receipt_profile: str,
    since_tick: int,
) -> int:
    """How many of ``subject_id``'s latest receipts in a row, for minutes from ``since_tick`` (the
    minute its play began), carried on with no answer from its person."""
    rows = connection.execute(
        "select document->>'reason' as reason from world_society_decision "
        "where workspace_id = %s and society_id = %s and document->>'profile' = %s "
        "and document->>'subject_id' = %s and (document->>'base_tick')::bigint >= %s "
        "order by decision_seq desc limit %s",
        (workspace_id, society_id, receipt_profile, subject_id, since_tick, QUIET_MINUTES),
    ).fetchall()
    count = 0
    for row in rows:
        if row["reason"] != "person_no_answer":
            break
        count += 1
    return count
