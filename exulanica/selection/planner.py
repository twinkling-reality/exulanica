"""The planner: a question in words, to a proposed Selection over the entities a session can see.

The planner is given a bounded catalogue of named entities by id and may choose only from it, and
it returns the plan rather than applying it: :mod:`exulanica.selection.question` validates, runs
and answers it. The question is sent as the request's
:class:`~exulanica.selection.request_names.RequestNames` makes it sendable, and the catalogue names
each entity the question named the same way.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import psycopg

from exulanica.epistemics.saved_names import PLACEHOLDER
from exulanica.models.client import ModelClient
from exulanica.models.errors import StructuredOutputError, TruncatedResponseError
from exulanica.models.manifest import Role
from exulanica.selection.calls import CallLog
from exulanica.selection.plan import SelectionPlan
from exulanica.selection.prompts import _EMPTY_CATALOGUE, _PLANNER_SYSTEM, PROMPT_VERSION
from exulanica.selection.request_names import RequestNames

__all__ = [
    "MAX_CATALOGUE",
    "PLANNER_ATTEMPTS",
    "EntityChoice",
    "entity_catalogue",
    "propose_plan",
]


#: How many entities the planner may be shown. A bound, because the catalogue goes into a prompt
#: and a library with a thousand named people would otherwise cost more than the answer.
MAX_CATALOGUE: Final = 60


#: How many times the planner may be asked before the question is refused. One try and one
#: repair. Named rather than written twice, because the loop bound and the give-up condition
#: used to be two literal 2s: widening the loop alone changed nothing, which made a test that
#: thought it was holding the retry bound hold nothing at all.
PLANNER_ATTEMPTS: Final = 2


@dataclass(frozen=True, slots=True)
class EntityChoice:
    """One entity the planner is allowed to reference, by id.

    A name reaches the planner only through this list, and only because a human already put it
    there: ``display_name`` is a cache of an active ``kind='user'`` naming assertion.
    """

    entity_id: uuid.UUID
    entity_class: str
    display_name: str


def entity_catalogue(
    connection: psycopg.Connection, workspace_id: uuid.UUID, *, limit: int = MAX_CATALOGUE
) -> tuple[EntityChoice, ...]:
    """The named entities this session may reference, most-seen first.

    Unnamed entities are excluded. An entity with no name is one the user has not identified,
    and offering the planner an id it cannot describe would let it filter by somebody the user
    has never met by name.
    """
    rows = connection.execute(
        "select e.entity_id, e.class, e.display_name, count(l.link_id) as seen "
        "from entity e left join entity_link l "
        "  on l.entity_id = e.entity_id and l.state = 'confirmed' "
        "where e.workspace_id = %s and e.deleted_at is null and e.display_name is not null "
        "and e.merged_into is null "
        "group by e.entity_id, e.class, e.display_name "
        "order by count(l.link_id) desc, e.entity_id limit %s",
        (workspace_id, limit),
    ).fetchall()
    return tuple(
        EntityChoice(
            entity_id=row["entity_id"],
            entity_class=row["class"],
            display_name=row["display_name"],
        )
        for row in rows
    )


def _catalogue_line(
    choice: EntityChoice, named: Mapping[uuid.UUID, str], names: RequestNames
) -> str:
    """One catalogue entry as the planner is sent it: an id and a class, and no other name.

    When the question named this entity, the entry adds it as the question is sent: a person by
    the placeholder the question was given, a place by the name the boundary releases or replaces
    with that placeholder. The plan can still refer to it by id either way.
    """
    reference = names.reference(choice.entity_id) if choice.entity_id in named else None
    return f"- {choice.entity_id} ({choice.entity_class})" + (f": {reference}" if reference else "")


_PLACEHOLDER_TEXT: Final = PLACEHOLDER


def _without_placeholders(plan: SelectionPlan, names: RequestNames) -> SelectionPlan:
    """A placeholder is never a search term, however the model spelled it, and nor is a name.

    The text dimension is joined, not ranked, so a placeholder the model copied into
    ``semantic_query`` would search for a class word and a letter and quietly discard every
    photograph that does not contain them. A named entity belongs in its own dimension, by id, and
    that holds for a place the planner was sent by name: its name in the query would discard every
    photograph of the place whose text does not spell it.

    Measured on the live planner, which also copies a placeholder without its brackets and in
    lower case: "person a" for "[person A]", in 4 draws of 5 on "Which photographs show" a named
    person. So each entity this request recorded is removed, its name first read as its
    placeholder, and each placeholder in any case and with or without brackets. Only those:
    elsewhere a class word followed by a letter is ordinary text.
    """
    if not plan.semantic_query:
        return plan
    remaining = _PLACEHOLDER_TEXT.sub(" ", names.labelled(plan.semantic_query))
    for label in names.placeholders.values():
        spelled = r"\s+".join(re.escape(word) for word in label.strip("[]").split())
        remaining = re.sub(rf"(?<!\w)\[?{spelled}\]?(?!\w)", " ", remaining, flags=re.IGNORECASE)
    if remaining == plan.semantic_query:
        return plan
    return plan.model_copy(update={"semantic_query": " ".join(remaining.split()) or None})


def propose_plan(
    client: ModelClient,
    question: str,
    catalogue: tuple[EntityChoice, ...],
    *,
    names: RequestNames,
    now: dt.datetime | None = None,
    log: CallLog | None = None,
) -> SelectionPlan:
    """Turn a question into a proposed Selection. Does not apply it.

    ADR-0005: "A natural-language turn produces a proposed Selection, shown to the user before
    it is applied." Returning it rather than running it is how that is enforced here; the caller
    decides whether a human has seen it.

    ``log`` collects what the calls actually cost and which model served them. It is optional
    because ``POST /selection/plan`` has nowhere to put the answer and asks for none.
    """
    # ``names`` is the request's record of every name the account holder has saved, and is
    # required, so no caller can plan without it. The question is sent with each name no right
    # can release replaced by its placeholder and each place's name left to the boundary, and the
    # catalogue names each entity the question named the same way, against its id, so the plan
    # can still refer to it.
    asked = names.sendable(question)
    named = names.placeholders
    catalogue_text = (
        "\n".join(_catalogue_line(choice, named, names) for choice in catalogue[:MAX_CATALOGUE])
        or _EMPTY_CATALOGUE
    )
    stamp = (now or dt.datetime.now(dt.UTC)).isoformat()
    # **The extraction role, and this is the case the manifest reserved it for.** Its rationale
    # says it is "not in any default route" and is "reserved for the case where the reasoning
    # core's json_schema conformance is measured to be unreliable, at which point the NVIDIA core
    # keeps the reasoning role and gives up the extraction role". That measurement had never been
    # taken; the extraction model was simply the default everywhere, which is how the NVIDIA core
    # ended up in no product path at all.
    #
    # Measured now, on this prompt and this schema against the live endpoint: the reasoning core
    # conforms, and needs 16384 tokens to do it where this one needs 2048, because it spends the
    # difference on inline reasoning it cannot be told to skip. Eight times the budget and eight
    # times the latency to fill in a form is the unreliability the escape clause describes, so
    # the escape clause applies and the reasoning core keeps the reasoning, which is
    # `compose_answer` in question.py.
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _PLANNER_SYSTEM},
        {
            "role": "user",
            "content": (f"Today is {stamp}.\n\nCatalogue:\n{catalogue_text}\n\nQuestion: {asked}"),
        },
    ]
    # **One repair, then refuse**, which is the composer's shape with a different floor under it.
    #
    # The endpoint enforces the JSON Schema, so a plan that gets here is already schema-valid.
    # What it can still break is a rule the schema cannot express: `_multi_entity_modes_need_two`
    # is a Pydantic model validator, invisible to the endpoint and invisible to the model.
    # Measured, on a library holding exactly one named entity: the planner chose mode 'all' over
    # that one id, which is unsatisfiable by construction, and the whole question failed with a
    # StructuredOutputError. The prompt now states the rule, and a prompt is not enforcement, so
    # the message the validator produced goes back to the model once.
    #
    # And then it refuses, where the composer falls back. There is no honest default plan: an
    # empty plan is legal and means "everything", so returning one would answer a question the
    # user did not ask and present it as the answer to the one they did.
    for attempt in range(1, PLANNER_ATTEMPTS + 1):
        try:
            proposed = client.structured(
                Role.STRUCTURED_EXTRACTION,
                messages,
                SelectionPlan,
                prompt_version=PROMPT_VERSION,
                placeholders=names.placeholders,
            )
            if log is not None:
                log.record(proposed.call)
            return _without_placeholders(proposed.value, names)
        except StructuredOutputError as rejected:
            if attempt == PLANNER_ATTEMPTS:
                raise
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "That form was refused:\n"
                        f"{rejected}\n\nFill it in again, fixing exactly that. Change nothing "
                        "else about what the question is asking for."
                    ),
                }
            )
        except TruncatedResponseError:
            # Measured on the live planner: a cross-content plan written correctly as far as its
            # scope and then whitespace until the token limit, in 2 draws of 5 on one question. A
            # plan is a small fraction of the role's limit, so this is the model running on, not
            # a budget too small for the answer, and asking again is the repair it needs. It
            # counts against the same attempts, and a second failure is raised as it always was.
            if attempt == PLANNER_ATTEMPTS:
                raise
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "That form ran on past its end and was cut off before it was complete. "
                        "Fill it in again, and stop at its closing brace."
                    ),
                }
            )
    raise AssertionError("unreachable: the loop above either returns or raises")
