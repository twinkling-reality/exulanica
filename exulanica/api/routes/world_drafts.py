"""A world's specification drafted from a person's own words: a proposal, and nothing made.

``POST /worlds/specification/drafts`` takes a description in the person's words and answers with a
proposal document, the same for the page and for an agent calling the API:

*   the words as they were typed;
*   the proposal: the preset it starts from and every value a person may set, which of them the
    words set, and the verdict of the same validation ``POST /worlds/generated`` applies to a
    person's own values, a refused value by name with the range and step it broke;
*   one sample town of those values, generated off the request's thread and labelled a sample
    (:mod:`exulanica.world.specification_samples`): its people, vehicles, streets and premises;
*   the parts of the words no value can say, each the person's own words;
*   or a refusal by name when nothing the words ask for is a world this server makes;
*   the specification, prompt and model it was drafted with, and what the drafting cost;
*   for a draft that is not refused, ``look_offer``: which of the library's looks the words ask
    for, if any, chosen by a short step of its own after the draft
    (:mod:`exulanica.selection.look_choosing`), with the person's own words that chose it. The
    drafter's request is the same whether or not the step runs; whatever the step answers, the
    person picks the look, and the library's default stands when it offers none.

Nothing is written. Making the world is the person's ``POST /worlds/generated`` with the preset and
values they confirm, the one gate every world passes. The route needs ``world.read`` and
``model.invoke``: it reads the specification and spends on a model, and writes no world.
"""

from __future__ import annotations

import dataclasses
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, get_services
from exulanica.api.routes.selection import ExecutionView, _execution, _require_model
from exulanica.epistemics.hosted_requests import borrowing, no_place_released
from exulanica.errors import PrivacyAdmissionError
from exulanica.models.client import ModelClient
from exulanica.models.errors import BudgetExceededError, ModelError
from exulanica.models.manifest import load_manifest
from exulanica.selection.calls import CallLog
from exulanica.selection.look_choosing import LookOption, choose_look, chooser_prompt
from exulanica.selection.world_drafting import (
    SentDescription,
    drafting_prompt,
    propose_world_specification,
    specification_view,
)
from exulanica.world import specification_source
from exulanica.world.specification_samples import TownSample, sample_worker
from exulanica.world.style_pack_library import style_pack_library

__all__ = ["router"]

router = APIRouter(prefix="/worlds", tags=["world"])

#: The longest description a draft reads, the prompt file's ceiling with its reason.
_DESCRIPTION_CHARACTERS = drafting_prompt().description_characters_maximum


class DraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Annotated[str, Field(min_length=1, max_length=_DESCRIPTION_CHARACTERS)]

    @field_validator("description")
    @classmethod
    def _says_something(cls, value: str) -> str:
        # A description of nothing but spaces would still cost a paid call.
        if not value.strip():
            raise ValueError("a description says in words what town is wanted")
        return value


class ValueRefusalView(BaseModel):
    """The validation's refusal of a proposed value, by name, with what it broke."""

    model_config = ConfigDict(extra="forbid")

    code: str
    detail: str
    key: str | None = None
    value: int | str | None = None
    minimum: int | None = None
    maximum: int | None = None
    step: int | None = None
    choices: list[str] = []
    #: For values that disagree, the other key and its value, which narrowed this one's range.
    with_key: str | None = None
    with_value: int | str | None = None


class CountedView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    #: The catalog's own word for the kind.
    label: str
    count: int


class SampleView(BaseModel):
    """One sample town of the proposed values, or why there is none. A made town draws its own
    identity, so its counts differ from the sample's."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["sampled", "refused", "overran", "busy", "unavailable"]
    tiles: int | None
    people: int | None
    vehicles: int | None
    vehicles_refused: str | None
    streets: list[CountedView]
    premises: list[CountedView]
    buildings: int | None
    refused: str | None


class ProposalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: str
    #: Every value a person may set, as the proposal would send it to ``POST /worlds/generated``.
    values: dict[str, int | str]
    #: The values the words set to other than the preset's, in the specification's order.
    set_by_words: list[str]
    fit: Literal["all", "part"]
    #: Whether the specification's own validation accepts the preset and values.
    valid: bool
    value_refusal: ValueRefusalView | None
    #: Present when the values are valid.
    sample: SampleView | None


class DraftRefusalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal["description_not_supported", "not_drafted"]
    detail: str


#: Why a look offer is none or unavailable.
LookReason = Literal["answer_refused", "timed_out", "failed", "request_refused", "no_allowance"]


class LookOfferView(BaseModel):
    """The look the words ask for, offered for the person to keep or change, or why there is none.

    ``offered`` names a library pack at its current version (``pack_id``, ``version`` and
    ``manifest_sha256``, so the page binds exactly what was offered) and the person's own words
    that chose it, as typed. ``none``: the step found no listed look in the words, or its answer
    was refused twice (``reason`` ``answer_refused``). ``unavailable``: the step could not be
    asked or did not answer (``reason`` ``timed_out``, ``failed``, ``request_refused`` or
    ``no_allowance``). Either way the world is made in the library's default unless the person
    picks a look, and the draft is unchanged.
    """

    model_config = ConfigDict(extra="forbid")

    state: Literal["offered", "none", "unavailable"]
    reason: LookReason | None
    pack_id: str | None
    version: int | None
    manifest_sha256: str | None
    #: The person's own words that chose the look, as typed: never a saved name.
    look_words: list[str]
    prompt_version: str
    prompt_sha256: str
    #: What the step cost to produce, its own attempts only; the draft's are in ``execution``.
    execution: ExecutionView


class WorldDraftView(BaseModel):
    """What a description drafted: a proposal to confirm, or a refusal, and how it was made."""

    model_config = ConfigDict(extra="forbid")

    #: The words as the person typed them.
    description: str
    proposal: ProposalView | None
    #: Each part of the words no value of the specification can say, in the person's own words:
    #: read from the description as typed, never from a saved name.
    not_supported: list[str]
    refusal: DraftRefusalView | None
    specification_version: int
    specification_sha256: str
    prompt_version: str
    prompt_sha256: str
    model_id: str | None
    #: The name a person reads for ``model_id`` (``Manifest.model_name``): no page derives one.
    model_name: str | None
    execution: ExecutionView
    #: Present for a draft that is not refused, while the library holds a look; absent otherwise.
    look_offer: LookOfferView | None = None


def _unavailable(failed: Exception) -> LookReason:
    if isinstance(failed, BudgetExceededError):
        return "no_allowance"
    if isinstance(failed, PrivacyAdmissionError):
        return "request_refused"
    ended = getattr(failed, "timed_out", False) or getattr(failed, "deadline_ended", False)
    return "timed_out" if ended else "failed"


def _look_offer(client: ModelClient, sent: SentDescription) -> LookOfferView | None:
    """Ask which listed look the words sent to the drafter ask for, after the draft. The step
    spends the same allowance the draft does, and its failure never fails the draft."""
    packs = {pack.pack_id: pack for pack in style_pack_library().packs}
    if not packs:
        return None
    prompt = chooser_prompt()
    options = tuple(
        LookOption(pack.pack_id, pack.title, pack.description) for pack in packs.values()
    )
    log = CallLog()
    state: Literal["offered", "none", "unavailable"]
    reason: LookReason | None
    pack = None
    words: list[str] = []
    try:
        choice = choose_look(
            client.with_attempts(log.attempt),
            sent.text,
            options,
            prompt=prompt,
            placeholders=sent.placeholders,
            log=log,
        )
    except (ModelError, PrivacyAdmissionError) as failed:
        state, reason = "unavailable", _unavailable(failed)
    else:
        reason = None if choice.refused is None else "answer_refused"
        pack = None if choice.look is None else packs[choice.look]
        state = "none" if pack is None else "offered"
        words = [sent.typed_words(start, end) for start, end in choice.look_words_at]
    return LookOfferView(
        state=state,
        reason=reason,
        pack_id=None if pack is None else pack.pack_id,
        version=None if pack is None else pack.version,
        manifest_sha256=None if pack is None else pack.manifest_sha256,
        look_words=words,
        prompt_version=prompt.prompt_version,
        prompt_sha256=prompt.sha256,
        execution=_execution(log.calls, (), prompt_version=prompt.prompt_version),
    )


def _sample(sample: TownSample) -> SampleView:
    return SampleView(
        status=sample.status,
        tiles=sample.tiles,
        people=sample.people,
        vehicles=sample.vehicles,
        vehicles_refused=sample.vehicles_refused,
        streets=[CountedView(key=c.key, label=c.label, count=c.count) for c in sample.streets],
        premises=[CountedView(key=c.key, label=c.label, count=c.count) for c in sample.premises],
        buildings=sample.buildings,
        refused=sample.refused,
    )


@router.post(
    "/specification/drafts",
    response_model=WorldDraftView,
    summary="Draft a world's specification from a description; nothing is made.",
)
def draft_world(
    body: DraftBody,
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> WorldDraftView:
    """Ask the specification drafter for a proposal of ``body.description``, validate it as a
    person's own values are validated, and sample one town of it when it is valid; make nothing.

    Answered 503 where the instance has no model credential, before the specification is read.
    """
    # The workspace's own client, with a policy that releases no place's name added after its
    # own: describing a world is no use a place-name right offers, so no grant reaches it. The
    # call site replaces every saved name as well; this makes the boundary hold it too.
    client = _require_model(request, connection, session).with_policy(
        get_services(request).request_policy(
            session.workspace_id, borrowing(connection), released_places=no_place_released
        )
    )
    view = specification_view(specification_source.served_document())
    prompt = drafting_prompt()
    outcome, sent = propose_world_specification(
        connection, client, body.description, session.workspace_id, view
    )
    draft = outcome.draft
    proposal = None
    if draft is not None:
        refused = specification_source.value_refusal(draft.preset, draft.values)
        refusal = (
            None
            if refused is None
            else ValueRefusalView(
                **{**dataclasses.asdict(refused), "choices": list(refused.choices)}
            )
        )
        proposal = ProposalView(
            preset=draft.preset,
            values=dict(draft.values),
            set_by_words=list(draft.set_by_words),
            fit=draft.fit,
            valid=refusal is None,
            value_refusal=refusal,
            sample=None
            if refusal is not None
            else _sample(sample_worker().sample(draft.preset, draft.values, view.sha256)),
        )
    return WorldDraftView(
        description=body.description,
        proposal=proposal,
        not_supported=[sent.typed_words(start, end) for start, end in outcome.not_supported_at],
        refusal=None
        if outcome.refusal is None
        else DraftRefusalView(code=outcome.refusal.code.value, detail=outcome.refusal.detail),
        specification_version=view.version,
        specification_sha256=view.sha256,
        prompt_version=prompt.prompt_version,
        prompt_sha256=prompt.sha256,
        model_id=outcome.model_id,
        model_name=None
        if outcome.model_id is None
        else load_manifest().model_name(outcome.model_id),
        execution=_execution(outcome.calls, (), prompt_version=prompt.prompt_version),
        look_offer=None if draft is None else _look_offer(client, sent),
    )
