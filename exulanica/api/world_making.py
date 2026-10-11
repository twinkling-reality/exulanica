"""A world made from a person's words, as one job the page polls.

``POST /worlds/drafts`` admits the words on the request's thread and starts a job here;
``GET /worlds/drafts/{draft_id}`` reads its state, for the person who started it only. No route
waits on a model. The job does, in order, saying which it is at:

*   **choosing**: it asks which tool of the world tool catalog should make the place
    (:mod:`exulanica.selection.tool_choosing`), shown only the words and each tool's own line. The
    catalog's tool for an unsure choice is taken when the step answers none, is refused twice or
    fails, and the draft records whether a model chose.
*   **drafting**: that tool's drafter writes what its composer takes: the kind drafter a whole
    kind document, held to both stages of the kind checks, or the specification drafter a town's
    preset and values, held to the gate every town passes.
*   **making**: the world is composed and its entry saved, as ``POST /worlds/kinds/{kind}/worlds``
    and ``POST /worlds/generated`` make one. The person meets no card, preset or value.

It ends ``ready`` with the saved entry, every part that was made (its words, its look role and
the box it is drawn in, where it has one) and the phrases of the description that were left out,
or ``refused`` by name; either way with every call it made.

A world made this way keeps no kind in the workspace: a site world's receipt carries its whole kind
document and regenerates from it alone, so nothing is lost, and the workspace's kept kinds are the
ones a person chose to keep. The job runs under the same holder and budgets as a kind's draft
(:mod:`exulanica.api.kind_drafts`, the world draft policy). Its state lives in this process: a
draft still running when the process stops is lost, what it had spent stands, and a world that
had already been made is among the person's worlds.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from typing import Any, Final

from exulanica.api.kind_drafts import KindDraft, KindDrafts, Opener, drafted_kind
from exulanica.models.client import ModelClient
from exulanica.models.errors import BudgetExceededError, ModelError
from exulanica.selection import kind_drafting, tool_choosing, world_drafting
from exulanica.selection.calls import CallLog
from exulanica.selection.tool_choosing import choose_tool
from exulanica.selection.world_drafting import (
    SentDescription,
    draft_world_specification,
    specification_view,
)
from exulanica.world import specification_source
from exulanica.world.composers import GeneratedWorldRefused
from exulanica.world.kinds.document import KindDocument
from exulanica.world.kinds.library import town_adapter
from exulanica.world.kinds.samples import SiteRefused
from exulanica.world.kinds.worker import KindWorkWaiting, WorkerComposer
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.world_tools import WorldTool, tool_for_unsure, world_tools
from exulanica.world.worlds import WorldLimitReached, WorldsReadOnly

__all__ = [
    "STAGES",
    "WORLD_DRAFT_CODES",
    "calls_at_most",
    "make_world",
    "site_parts",
    "town_parts",
]

_LOG = logging.getLogger(__name__)

#: The steps a draft of a world is at while it runs, in order.
STAGES: Final = ("choosing", "drafting", "making")

#: Every code a world's draft ends refused with besides a kind draft's own
#: (:data:`exulanica.api.kind_drafts.KIND_DRAFT_CODES`) and the checks' codes, and what it means.
WORLD_DRAFT_CODES: Final = (
    ("world_not_a_place", "The words ask for no place where people could live, walk or work."),
    ("world_not_drafted", "No world could be drafted from the words."),
    ("world_draft_unanswered", "The model did not answer in time."),
    (
        "world_draft_model_failed",
        "The model's provider failed or refused the call, or could not be reached.",
    ),
    ("world_draft_failed", "The draft stopped before a world was made."),
    ("world_limit_reached", "The workspace already holds as many worlds as it may."),
    ("tile_budget_reached", "The workspace's worlds have come to as many tiles as a day allows."),
    ("worlds_read_only", "This server's database role cannot register a world."),
)
_FAILED: Final = {
    "code": "world_draft_failed",
    "detail": "The draft stopped before a world was made. Say it again.",
}


def calls_at_most() -> int:
    """The most times one draft of a world asks a model: the chooser's call and its repair, then
    the attempts of whichever listed tool's drafter makes the most. Counted from the steps' own
    bounds, so the figure a person is shown before sending is the one the job is held to. A
    model withdrawn mid-call may be asked again through its fallback, which the spending
    allowance bounds and this figure does not count."""
    drafting = {
        "kind": kind_drafting.DRAFT_ATTEMPTS,
        "specification": world_drafting.DRAFT_ATTEMPTS,
    }
    return tool_choosing.ATTEMPTS + max(drafting[tool.drafter] for tool in world_tools())


def site_parts(kind: KindDocument, drawing: object) -> tuple[dict[str, Any], ...]:
    """Every part of a made site world: its key, words, form and look role, how many slots the
    world's drawing draws for it and the largest box among them (width, depth and height in
    millimetres), or no box where the part is not drawn as a thing of its own."""
    body = json.loads(drawing) if isinstance(drawing, str | bytes) else drawing
    slots = body.get("slots", []) if isinstance(body, Mapping) else []
    made = []
    for part in kind.parts.values():
        mine = [
            slot["boxMm"]
            for slot in slots
            if slot.get("part") == part.key and slot.get("lookRole") == part.look.role
        ]
        made.append(
            {
                "key": part.key,
                "label": part.label,
                "form": part.form,
                "look": part.look.role,
                "drawn": len(mine),
                "box_mm": max(mine, key=lambda box: box[0] * box[1] * max(box[2], 1))
                if mine
                else None,
            }
        )
    return tuple(made)


def town_parts() -> tuple[dict[str, Any], ...]:
    """The parts a town is made of, in the town adapter's words: a town's records are generated
    by the city grammar, so its parts state no box of their own."""
    return tuple(
        {
            "key": str(part["key"]),
            "label": str(part["label"]),
            "form": str(part["form"]),
            "look": str(part["look"]),
            "drawn": None,
            "box_mm": None,
        }
        for part in town_adapter().document["parts"]
    )


def _model_refusal(failed: ModelError) -> dict[str, Any]:
    """A model's error as a draft's refusal: a spent allowance, a silence, or a failed provider,
    each said as what it is."""
    from exulanica.models.errors import TransportError
    from exulanica.models.spending import SpendingRefused

    if isinstance(failed, BudgetExceededError):
        refusal: dict[str, Any] = {
            "code": "budget_exceeded",
            "detail": "This server's own spending limit for models is reached.",
        }
        if isinstance(failed, SpendingRefused):
            refusal["detail"] = str(failed)
            refusal["spending"] = failed.problem_member()
        return refusal
    if isinstance(failed, TransportError) and (failed.timed_out or failed.deadline_ended):
        return {
            "code": "world_draft_unanswered",
            "detail": "The model did not answer in time. Try again in a moment.",
        }
    return {
        "code": "world_draft_model_failed",
        "detail": (
            "The model's provider failed or refused the call, or could not be reached. "
            "Try again in a moment."
        ),
    }


def make_world(
    draft: KindDraft,
    drafts: KindDrafts,
    *,
    client: ModelClient,
    opened: Opener,
    actor: uuid.UUID,
    sent: SentDescription,
    store: Any,
    guest: bool,
    fixed_world_id: str | None = None,
) -> None:
    """Choose the tool for ``sent`` (the words as sent, every saved name replaced), draft with it
    and make the world, leaving the draft ``ready`` with its saved entry or ``refused`` by name,
    with every call it made either way.

    ``opened`` opens a connection scoped to the draft's workspace that may write; none is held
    while a model runs. ``fixed_world_id`` fixes the world's identity instead of drawing one, so a
    test makes the same world every run."""
    log = CallLog()

    def refused(refusal: Mapping[str, Any]) -> None:
        drafts.finish(draft, state="refused", refusal=dict(refusal), calls=log.calls)

    drafts.advance(draft, stage="choosing")
    tool: WorldTool | None = None
    try:
        choice = choose_tool(
            client.with_attempts(log.attempt),
            sent.text,
            world_tools(),
            placeholders=sent.placeholders,
            log=log,
        )
        tool = next((one for one in world_tools() if one.key == choice.tool), None)
    except BudgetExceededError as spent:
        # No allowance is left for any step after this one either.
        refused(_model_refusal(spent))
        return
    except Exception as failed:
        # The step is optional: whatever stopped it (a model's error, a request the workspace's
        # rules refused, a fault of its own), the catalog's tool for an unsure choice stands.
        if not isinstance(failed, ModelError):
            _LOG.warning("the tool chooser failed: %s", type(failed).__qualname__)
        tool = None
    chosen = tool is not None
    tool = tool_for_unsure() if tool is None else tool
    drafts.advance(draft, stage="drafting", tool=tool.key, tool_chosen=chosen)

    path = _make_place if tool.drafter == "kind" else _make_town
    try:
        path(draft, drafts, log, client, opened, actor, sent, store, guest, fixed_world_id)
    except Exception as failed:  # anything unnamed, after paid calls, still shows what it cost
        _LOG.warning("a world draft failed: %s", type(failed).__qualname__)
        refused(_FAILED)


def _saved(
    draft: KindDraft,
    drafts: KindDrafts,
    log: CallLog,
    make: Any,
) -> Any | None:
    """Run ``make`` (the composing and saving of one world) and answer its entry, or None after
    ending the draft refused by the making's own name."""

    def refused(refusal: Mapping[str, Any]) -> None:
        drafts.finish(draft, state="refused", refusal=dict(refusal), calls=log.calls)

    try:
        return make()
    except SiteRefused as none_fits:
        sentences = "; ".join(str(refusal.get("refusal", "")) for refusal in none_fits.refusals[:2])
        refused({"code": none_fits.code, "detail": sentences})
    except GeneratedWorldRefused as none_generates:
        refused({"code": none_generates.code, "detail": str(none_generates)})
    except WorldLimitReached as full:
        refused({"code": full.code, "detail": str(full)})
    except WorldsReadOnly as read_only:
        refused({"code": read_only.code, "detail": str(read_only)})
    except KindWorkWaiting as waiting:
        refused({"code": waiting.code, "detail": str(waiting)})
    return None


def _make_place(
    draft: KindDraft,
    drafts: KindDrafts,
    log: CallLog,
    client: ModelClient,
    opened: Opener,
    actor: uuid.UUID,
    sent: SentDescription,
    store: Any,
    guest: bool,
    fixed_world_id: str | None,
) -> None:
    outcome = drafted_kind(
        draft,
        drafts,
        client=client,
        text=sent.text,
        placeholders=sent.placeholders,
        log=log,
        # No key is reserved: the kind is not kept, and the world's receipt carries it whole.
        key_for=None,
    )
    if outcome is None or outcome.kind is None:
        return
    kind = outcome.kind
    if drafts.closing:
        # The server is stopping: nothing new is composed, and nothing was made.
        drafts.finish(draft, state="refused", refusal=dict(_FAILED), calls=log.calls)
        return
    drafts.advance(draft, stage="making")
    composer = WorkerComposer(draft.workspace_id)

    def make() -> Any:
        with opened() as connection:
            entries = SavedWorldEntryRepository(connection, draft.workspace_id, store, guest=guest)
            return entries.create_from_kind(
                title=kind.label,
                kind=kind,
                values=kind.values(kind.presets[0][0]),
                created_by=actor,
                compose=composer,
                fixed_world_id=fixed_world_id,
            )

    created = _saved(draft, drafts, log, make)
    if created is None:
        return
    # The world exists from here on, so the draft ends ready whatever follows.
    try:
        # The drawing the page reads next and the place its people walk, made with the world.
        composer.keep()
        drawing = None if composer.drawn is None else composer.drawn[1]["body"]
        made = site_parts(kind, drawing)
    except Exception as failed:
        _LOG.warning("a made world's parts were not counted: %s", type(failed).__qualname__)
        made = site_parts(kind, None)
    drafts.made(
        draft,
        entry_id=created.entry_id,
        made=made,
        left_out=(),
        calls=log.calls,
        model_id=outcome.model_id,
    )


def _make_town(
    draft: KindDraft,
    drafts: KindDrafts,
    log: CallLog,
    client: ModelClient,
    opened: Opener,
    actor: uuid.UUID,
    sent: SentDescription,
    store: Any,
    guest: bool,
    fixed_world_id: str | None,
) -> None:
    def refused(refusal: Mapping[str, Any]) -> None:
        drafts.finish(draft, state="refused", refusal=dict(refusal), calls=log.calls)

    view = specification_view(specification_source.served_document())
    try:
        outcome = draft_world_specification(
            client.with_attempts(log.attempt),
            sent.text,
            view,
            placeholders=sent.placeholders,
            log=log,
        )
    except ModelError as failed:
        refused(_model_refusal(failed))
        return
    town = outcome.draft
    if town is None:
        stated = outcome.refusal
        not_a_place = stated is not None and stated.code.value == "description_not_supported"
        refused(
            {
                "code": "world_not_a_place" if not_a_place else "world_not_drafted",
                "detail": "" if stated is None else stated.detail,
            }
        )
        return
    value = specification_source.value_refusal(town.preset, town.values)
    if value is not None:
        refused({"code": value.code, "detail": value.detail})
        return
    label = next(
        (
            str(preset["label"])
            for preset in specification_source.served_document()["presets"]
            if preset["key"] == town.preset
        ),
        "A town",
    )
    # Said before the making, so a world that was made is never then reported as not made.
    made = town_parts()
    left_out = tuple(sent.typed_words(start, end) for start, end in outcome.not_supported_at)
    if drafts.closing:
        refused(_FAILED)
        return
    drafts.advance(draft, stage="making")

    def make() -> Any:
        with opened() as connection:
            entries = SavedWorldEntryRepository(connection, draft.workspace_id, store, guest=guest)
            return entries.create_generated(
                title=label,
                recipe_key=town.preset,
                created_by=actor,
                values=town.values,
                fixed_world_id=fixed_world_id,
            )

    created = _saved(draft, drafts, log, make)
    if created is None:
        return
    drafts.made(
        draft,
        entry_id=created.entry_id,
        made=made,
        left_out=left_out,
        calls=log.calls,
        model_id=outcome.model_id,
    )
