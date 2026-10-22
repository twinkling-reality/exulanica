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
    and ``POST /worlds/generated`` make one. The person meets no card, preset or value. Where the
    server makes places on land (``EXULANICA_WORLDS_ON_LAND``), a place stands on the land its
    words, its setting or the default name (:mod:`exulanica.world.land_choice`), or on level
    ground where no layout of it fits that land, and the draft says which.

It ends ``ready`` with the saved entry, every part that was made (its words, its look role and
the box it is drawn in, where it has one) and the phrases of the description that were left out,
or ``refused`` by name; either way with every call it made.

A world made this way keeps no kind in the workspace: a site world's receipt carries its whole kind
document and regenerates from it alone, so nothing is lost, and the workspace's kept kinds are the
ones a person chose to keep. The job runs under the same holder and budgets as a kind's draft
(:mod:`exulanica.api.kind_drafts`, the world draft policy). Its request, progress and outcome are
kept in the database (migration 0207): a draft whose process stopped while it ran is not asked
again, and ends ready where its world was already made or refused ``world_draft_interrupted``,
with what it had spent recorded either way (:mod:`exulanica.api.world_draft_worker`).

A town takes tiles from the workspace's day (the world-count policy's tiles a day), so the town
tool asks that budget before each paid step that could only end in its refusal: before the town is
drafted, for the one tile every town takes, and before its look and setting are chosen, for the
drafted town's own. The making asks it again under the workspace's lock, where the answer holds.
"""

from __future__ import annotations

import functools
import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from exulanica.api.kind_drafts import KindDraft, KindDrafts, Opener, budget_refusal, drafted_kind
from exulanica.api.world_draft_offer import calls_at_most as counted_calls
from exulanica.grammar.catalogs import CatalogSchema, load_catalog, text_field
from exulanica.grammar.landform import LandformRefused
from exulanica.models.client import ModelClient
from exulanica.models.errors import BudgetExceededError, ModelError
from exulanica.models.manifest import load_manifest
from exulanica.selection.calls import CallLog
from exulanica.selection.look_choosing import LookOption, choose_look
from exulanica.selection.setting_choosing import SettingAxis, SettingOption, choose_setting
from exulanica.selection.tool_choosing import choose_tool
from exulanica.selection.world_drafting import (
    SentDescription,
    draft_world_specification,
    specification_view,
)
from exulanica.world import specification_source
from exulanica.world.composers import GeneratedWorldRefused
from exulanica.world.creation_look import name_creation_look
from exulanica.world.errors import StyleWriteBusy
from exulanica.world.kinds.document import KindDocument
from exulanica.world.kinds.library import town_adapter
from exulanica.world.kinds.samples import SiteRefused
from exulanica.world.kinds.worker import KindWorkWaiting, WorkerComposer
from exulanica.world.land_choice import LandChoice, choose_land, said_by_land
from exulanica.world.models import StylePackBinding
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.style_pack_library import style_pack_context, style_pack_library
from exulanica.world.style_packs import StylePackRefused
from exulanica.world.world_recipes import town_recipe
from exulanica.world.world_settings import SettingRefused, bound_setting, setting_parts
from exulanica.world.world_tools import WorldTool, tool_for_unsure, world_tools
from exulanica.world.worlds import (
    GENERATED,
    WorldLimitReached,
    WorldsReadOnly,
    refuse_past_limit,
)

__all__ = [
    "STAGES",
    "WORLD_DRAFT_CODES",
    "calls_at_most",
    "guarded",
    "make_world",
    "site_parts",
    "title_from_words",
    "title_joining_words",
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
#: How long a draft's making waits for a place on land: no request waits on a draft's job, and
#: grading a layout on land takes longer than on level ground (6 to 11 s a world on the
#: development machine's copy, one over the route's 15 s once under heavy load, 14 October 2026),
#: so four times the route's limit, within the kind worker's bound for a stuck job.
LAND_COMPOSE_SECONDS: Final = 60.0


def calls_at_most(client: ModelClient | None) -> int:
    """The most times one draft of a world asks a model, counted as its operation sheet counts
    them (:func:`exulanica.api.world_draft_offer.calls_at_most`): every schema repair of every
    step along the longer tool's path, each step's request sent to every model of its chain as
    often as ``client`` tries one. With no client, each model is counted once, as the server's own
    client (one attempt a model) asks it. So the figure a person is shown before sending is the
    same whether or not the server could read prices, and never less than the job may do."""
    if client is None:
        manifest = load_manifest()
        return counted_calls(manifest, lambda role: len(manifest[role].chain))
    return counted_calls(client.manifest, client.maximum_wire_attempts)


Span = tuple[int, int]


def guarded(
    look: str | None,
    look_words_at: Sequence[Span],
    parts: Mapping[str, str],
    words_at: Sequence[Span],
) -> tuple[str | None, dict[str, str]]:
    """What the job TAKES of the two steps' answers: stricter than what a person is offered,
    since nobody picks. A part invented is worse than a part missed, so:

    *   the parts of a setting are taken only when the answer copied at least as many phrases as
        it names parts, and otherwise none is: one phrase list serves every axis, so a single
        phrase can carry a part for each axis and only one of them be the person's;
    *   a look is not taken when every phrase that chose it overlaps a phrase that chose a kept
        part of the setting: words about the hour or the weather ask for a sky, not a look.

    It counts phrases and binds none to an axis, so it bounds an invention and does not prove
    each part: an answer padded with as many phrases as parts passes it."""
    kept = dict(parts) if len(words_at) >= len(parts) else {}

    def overlaps(one: Span, other: Span) -> bool:
        return one[0] < other[1] and other[0] < one[1]

    weather = bool(kept and look_words_at) and all(
        any(overlaps(mine, theirs) for theirs in words_at) for mine in look_words_at
    )
    return (None if weather else look), kept


@dataclass(frozen=True, slots=True)
class _Taken:
    """The look and the parts of a setting the job took from the words, as a draft says them."""

    look: dict[str, Any] | None = None
    setting: dict[str, Any] | None = None
    #: Where in the words as sent the phrases stand that chose what was taken.
    spans: tuple[Span, ...] = ()

    @property
    def pack_id(self) -> str | None:
        return None if self.look is None else str(self.look["pack_id"])

    @property
    def parts(self) -> dict[str, str]:
        chosen = [] if self.setting is None else self.setting["parts"]
        return {str(part["axis"]): str(part["key"]) for part in chosen}


#: The most characters of a person's sentence a town made from it takes as its title.
TITLE_FROM_WORDS_CHARACTERS: Final = 48
#: The joining words a title cut from a person's sentence never ends on, each with why.
TITLE_JOINING_WORDS_PATH: Final = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "catalogs"
    / "world-titles"
    / "title-joining-word.v1.json"
)
_TITLE_JOINING_WORD: Final = CatalogSchema(
    "title-joining-word", 1, (("class", text_field), ("reason", text_field))
)


@functools.cache
def title_joining_words(path: Path = TITLE_JOINING_WORDS_PATH) -> frozenset[str]:
    """The articles, determiners, prepositions, conjunctions and relative words the catalog at
    ``path`` lists: a title cut short drops them from its end, since each joins on to words the
    title no longer holds."""
    return frozenset(entry.key for entry in load_catalog(path, _TITLE_JOINING_WORD).entries)


def title_from_words(sent: SentDescription) -> str | None:
    """The title of a town made from a person's words, taken from them: their sentence as typed
    up to its first comma, or its first 48 characters ending on a whole word where it runs longer,
    with a capital first letter and no full stop. It claims nothing the person did not write and
    carries no saved name: where one stands inside it (a span the drafting replaced, as typed), it
    ends before that name. Cut short in any of these ways, it never ends on a joining word
    (:func:`title_joining_words`). None where fewer than two words are left, and the town keeps
    its preset's label."""
    typed = sent.typed
    start = len(typed) - len(typed.lstrip())
    comma = typed.find(",", start)
    end = len(typed) if comma < 0 else comma
    cut = comma >= 0
    for _sent_start, _sent_end, typed_start, _typed_end in sent.replaced:
        if start <= typed_start < end:
            end, cut = typed_start, True
            break
    clause = " ".join(typed[start:end].split())
    if len(clause) > TITLE_FROM_WORDS_CHARACTERS:
        within = clause[: TITLE_FROM_WORDS_CHARACTERS + 1]
        clause, cut = (within[: within.rfind(" ")] if " " in within else ""), True
    words = clause.rstrip(" .,;:").split()
    joining = title_joining_words() if cut else frozenset()
    while words and words[-1].rstrip(".,;:").casefold() in joining:
        words.pop()
    title = " ".join(words).rstrip(" .,;:")
    if len(title.split()) < 2:
        return None
    return title[0].upper() + title[1:]


def _take(client: ModelClient, sent: SentDescription, log: CallLog) -> _Taken:
    """Ask the look chooser and the setting chooser what the words as sent ask for, as the town's
    draft route asks them, and take what the guards leave. Either step failing, being refused or
    answering none takes nothing and never fails the draft, an allowance that ran out included:
    the draft itself is paid for and good, and a world in the default look is better than none."""
    # Only the looks the step's recorded runs were measured with, as the town's draft route
    # offers it (the library file lists them): any other pack is a look a person chooses.
    library = style_pack_library()
    packs = {pack.pack_id: pack for pack in library.packs if pack.pack_id in library.chooser_offers}
    listed = setting_parts()
    look, look_at = None, ()
    parts: Mapping[str, str] = {}
    words_at: Sequence[Span] = ()
    if packs:
        try:
            choice = choose_look(
                client.with_attempts(log.attempt),
                sent.text,
                tuple(LookOption(p.pack_id, p.title, p.description) for p in packs.values()),
                placeholders=sent.placeholders,
                log=log,
            )
            look, look_at = choice.look, choice.look_words_at
        except Exception as failed:
            _LOG.warning("the look chooser took nothing: %s", type(failed).__qualname__)
    if listed.parts:
        try:
            answer = choose_setting(
                client.with_attempts(log.attempt),
                sent.text,
                tuple(SettingAxis(key, title) for key, title in listed.axes),
                tuple(SettingOption(**part) for part in listed.listed()),
                placeholders=sent.placeholders,
                log=log,
            )
            parts, words_at = answer.parts, answer.words_at
        except Exception as failed:
            _LOG.warning("the setting chooser took nothing: %s", type(failed).__qualname__)
    kept_look, kept_parts = guarded(look, look_at, parts, words_at)
    titles = {(part["axis"], part["key"]): part["title"] for part in listed.listed()}
    try:
        # The person's own words, every saved name put back; a phrase that cuts a replaced name
        # cannot be said back, and what it chose is then not taken either.
        said_look = [sent.typed_words(start, end) for start, end in look_at]
        said_parts = [sent.typed_words(start, end) for start, end in words_at]
    except Exception as failed:
        _LOG.warning("a chosen phrase could not be said back: %s", type(failed).__qualname__)
        return _Taken()
    return _Taken(
        look=None
        if kept_look is None
        else {"pack_id": kept_look, "title": packs[kept_look].title, "words": said_look},
        setting=None
        if not kept_parts
        else {
            "parts": [
                {"axis": axis, "key": key, "title": titles[(axis, key)]}
                for axis, key in kept_parts.items()
            ],
            "words": said_parts,
        },
        spans=(*(look_at if kept_look is not None else ()), *(words_at if kept_parts else ())),
    )


def _left_out(
    sent: SentDescription, spans: Sequence[Span], taken: Sequence[Span]
) -> tuple[str, ...]:
    """The phrases of the description nothing in the made world says, in the person's own words.
    A phrase that chose a look or a part of the setting the job took is said by that and is not
    left out. A phrase that cuts a replaced name cannot be said back and is dropped, never the
    failure of a draft that is paid for."""
    said = []
    for start, end in spans:
        if any(start < theirs_end and theirs_start < end for theirs_start, theirs_end in taken):
            continue
        try:
            said.append(sent.typed_words(start, end))
        except Exception as failed:
            _LOG.warning("a left-out phrase could not be said back: %s", type(failed).__qualname__)
    return tuple(said)


def _dress(
    opened: Opener,
    draft: KindDraft,
    store: Any,
    guest: bool,
    actor: uuid.UUID,
    created: Any,
    taken: _Taken,
) -> _Taken:
    """Name the look the made world is drawn in, as ``POST /worlds/generated`` names a town's: the
    look that was taken or else the library's default, with the parts of the setting that were
    taken composed for that pack. Answers what the world then wears. A setting the pack cannot be
    drawn in is left off and the world keeps the look; a look that cannot be written now leaves
    the world as made, in the default look. Never a refusal: the world exists."""
    library = style_pack_library()
    packs = {pack.pack_id: pack for pack in library.packs}
    pack = packs.get(taken.pack_id or "", library.default_pack)
    setting = None
    worn = taken
    if taken.parts:
        chain = library.chain(pack.manifest_sha256)
        try:
            setting = (
                None
                if chain is None
                else bound_setting(chain, style_pack_context(), chosen=taken.parts)
            )
        except (SettingRefused, StylePackRefused) as refused:
            _LOG.warning("a taken setting was left off: %s", type(refused).__qualname__)
        if setting is None:
            worn = _Taken(look=taken.look)
    binding = StylePackBinding(pack.pack_id, pack.version, pack.manifest_sha256, setting=setting)
    try:
        with opened() as connection:
            entries = SavedWorldEntryRepository(connection, draft.workspace_id, store, guest=guest)
            name_creation_look(entries, created, binding, actor)
    except StyleWriteBusy:
        return _Taken()
    return worn


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

    if isinstance(failed, BudgetExceededError):
        return budget_refusal(failed)
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


def _worn(
    opened: Opener,
    draft: KindDraft,
    store: Any,
    guest: bool,
    actor: uuid.UUID,
    created: Any,
    taken: _Taken,
) -> _Taken:
    """What the made world wears once its look is named, or nothing where naming it failed: the
    world exists, so whatever happens here it is ready."""
    try:
        return _dress(opened, draft, store, guest, actor, created, taken)
    except Exception as failed:
        _LOG.warning("a made world's look was not named: %s", type(failed).__qualname__)
        return _Taken()


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
    on_land: bool = False,
) -> None:
    """Choose the tool for ``sent`` (the words as sent, every saved name replaced), draft with it
    and make the world, leaving the draft ``ready`` with its saved entry or ``refused`` by name,
    with every call it made either way. With ``on_land`` a place or a town stands on land chosen
    from what was said, or on level ground when none of its layouts fits that land.

    ``opened`` opens a connection scoped to the draft's workspace that may write; none is held
    while a model runs. ``fixed_world_id`` fixes the world's identity instead of drawing one: the
    world draft job passes its draft's own, so a draft taken up again after a restart finds the
    world it made, and a test makes the same world every run."""
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

    try:
        if tool.drafter == "kind":
            _make_place(
                draft,
                drafts,
                log,
                client,
                opened,
                actor,
                sent,
                store,
                guest,
                fixed_world_id,
                on_land,
            )
        else:
            _make_town(
                draft,
                drafts,
                log,
                client,
                opened,
                actor,
                sent,
                store,
                guest,
                fixed_world_id,
                on_land,
            )
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
    on_land: bool,
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
    taken = _take(client, sent, log)
    if drafts.closing:
        # The server is stopping: nothing new is composed, and nothing was made.
        drafts.finish(draft, state="refused", refusal=dict(_FAILED), calls=log.calls)
        return
    drafts.advance(draft, stage="making")
    land = (
        choose_land(
            sent.text,
            taken.parts.get("ground"),
            names=[(start, end) for start, end, _, _ in sent.replaced],
        )
        if on_land
        else None
    )
    composer = (
        WorkerComposer(draft.workspace_id)
        if land is None
        else WorkerComposer(draft.workspace_id, land=land.recipe.land, seconds=LAND_COMPOSE_SECONDS)
    )
    fell_back = False

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

    def made_or_once_more() -> Any:
        # A worker busy or slow for a moment is asked once more before a paid draft is discarded:
        # its finished work is kept, so the second ask usually reads it.
        try:
            return make()
        except KindWorkWaiting:
            return make()

    def made_on_its_land() -> Any:
        nonlocal composer, fell_back
        if land is None:
            return made_or_once_more()
        try:
            return made_or_once_more()
        except (SiteRefused, LandformRefused):
            # No layout of the place fits its land: it is made on level ground, and said so.
            fell_back = True
            composer = WorkerComposer(draft.workspace_id)
            return made_or_once_more()

    created = _saved(draft, drafts, log, made_on_its_land)
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
    worn = _worn(opened, draft, store, guest, actor, created, taken)
    # A phrase the drafter could not make that names only the land the place stands on ("in a
    # valley") is said by that land; one that asks for more of it ("sea with flying boats") is not.
    omitted = tuple(
        span
        for span in outcome.not_supported_at
        if land is None or fell_back or not said_by_land(sent.text[span[0] : span[1]], land.recipe)
    )
    drafts.made(
        draft,
        entry_id=created.entry_id,
        made=made,
        # Site omissions describe content/geometry/behavior. An overlapping setting phrase
        # cannot fulfill one: sea beyond the site does not add a harbour basin or a boat.
        left_out=_left_out(sent, omitted, ()),
        look=worn.look,
        setting=worn.setting,
        land=None if land is None else _land_taken(sent, land, fell_back=fell_back),
        calls=log.calls,
        model_id=outcome.model_id,
    )


def _land_taken(sent: SentDescription, land: LandChoice, *, fell_back: bool) -> dict[str, Any]:
    """What a draft says of the land its place stands on: the recipe, what chose it with the
    person's own words where words did, and whether the place was made on level ground instead."""
    try:
        words = [sent.typed_words(start, end) for start, end in land.spans]
    except Exception as failed:
        _LOG.warning("a land word could not be said back: %s", type(failed).__qualname__)
        words = []
    return {
        "recipe": land.recipe.key,
        "title": land.recipe.title,
        "chosen_by": land.chosen_by,
        "words": words,
        "fell_back": fell_back,
    }


#: The tiles every town covers at least: whole 128 m tiles, never none.
_TOWN_TILES_LEAST: Final = 1


def _past_the_day(
    opened: Opener, draft: KindDraft, guest: bool, tiles: int
) -> dict[str, Any] | None:
    """The refusal a town of ``tiles`` tiles would meet at its making, asked before a paid step
    rather than after it: the worlds the workspace may hold, then the tiles its worlds may come to
    today, as :func:`exulanica.world.worlds.refuse_past_limit` reads them. Unlocked, so an early
    answer and never a permission: the making asks again under the workspace's lock."""
    with opened() as connection:
        try:
            refuse_past_limit(connection, draft.workspace_id, GENERATED, guest=guest, tiles=tiles)
        except WorldLimitReached as full:
            return {"code": full.code, "detail": str(full)}
    return None


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
    on_land: bool,
) -> None:
    def refused(refusal: Mapping[str, Any]) -> None:
        drafts.finish(draft, state="refused", refusal=dict(refusal), calls=log.calls)

    full = _past_the_day(opened, draft, guest, _TOWN_TILES_LEAST)
    if full is not None:
        refused(full)
        return
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
    full = _past_the_day(opened, draft, guest, len(town_recipe(town.preset, town.values).tiles))
    if full is not None:
        refused(full)
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
    taken = _take(client, sent, log)
    if drafts.closing:
        refused(_FAILED)
        return
    drafts.advance(draft, stage="making")
    land = (
        choose_land(
            sent.text,
            taken.parts.get("ground"),
            names=[(start, end) for start, end, _, _ in sent.replaced],
        )
        if on_land
        else None
    )
    fell_back = False

    def make(on: LandChoice | None) -> Any:
        with opened() as connection:
            entries = SavedWorldEntryRepository(connection, draft.workspace_id, store, guest=guest)
            return entries.create_generated(
                title=title_from_words(sent) or label,
                recipe_key=town.preset,
                created_by=actor,
                values=town.values,
                fixed_world_id=fixed_world_id,
                land=None if on is None else on.recipe.land,
            )

    def made_on_its_land() -> Any:
        nonlocal fell_back
        if land is None:
            return make(None)
        try:
            return make(land)
        except (GeneratedWorldRefused, LandformRefused):
            # No candidate of the town stands on its land: it is made on level ground, and said so.
            fell_back = True
            return make(None)

    created = _saved(draft, drafts, log, made_on_its_land)
    if created is None:
        return
    worn = _worn(opened, draft, store, guest, actor, created, taken)
    # A phrase the drafter could not make that names only the land the town stands on is said by
    # that land, as for a place.
    omitted = tuple(
        span
        for span in outcome.not_supported_at
        if land is None or fell_back or not said_by_land(sent.text[span[0] : span[1]], land.recipe)
    )
    drafts.made(
        draft,
        entry_id=created.entry_id,
        made=made,
        left_out=_left_out(sent, omitted, taken.spans),
        look=worn.look,
        setting=worn.setting,
        land=None if land is None else _land_taken(sent, land, fell_back=fell_back),
        calls=log.calls,
        model_id=outcome.model_id,
    )
