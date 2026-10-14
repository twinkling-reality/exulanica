"""The Companion planner's vocabulary: its bounds, the kinds of action and operation it drafts, the
words it refuses and clarifies with, and the matrix of each prepared operation and the routes it is
sent to.

:mod:`exulanica.selection.action_plan` drafts and prepares plans in these terms. It imports the
names it uses from here, and names again the few that callers read from it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role
from exulanica.selection import action_budget, action_minds, action_things
from exulanica.world.object_repository import WorldObjectRepository

#: One try and one repair for the drafter, then a refusal; the classifier is asked once and a
#: failure is a question, as the appearance path's is.
DRAFT_ATTEMPTS: Final = 2
CLASSIFIER_CALLS: Final = 1
#: The most a drafter's reply may spend, the role's floor (the chain's fallback reasons inline
#: before it answers). A filled form is a few dozen tokens, so this is room, not a squeeze. A reply
#: that runs on fills whatever ceiling it is given, so a lower one is what bounds the wait for a
#: reply that will be refused: it ends inside the role's timeout rather than at it.
DRAFT_MAX_TOKENS: Final = 640
#: Every hosted call one utterance can make on this path, as the role and the most times it is
#: sent: the classifier, then one drafter and its repair (world edit, appearance or simulation,
#: never two of them).
ACTION_PATH_CALLS: Final[tuple[tuple[Role, int], ...]] = (
    (Role.STRUCTURED_EXTRACTION, CLASSIFIER_CALLS + DRAFT_ATTEMPTS),
)

#: How many changes one request may ask for, and how many options one step may name: a kind and
#: up to three things it could go beside, or a being and the places it could be asked to.
MAX_STEPS: Final = 8
MAX_CANDIDATES: Final = 4
#: How many of a version's objects the drafter is shown: the newest, and the selected one always.
MAX_OBJECT_CHOICES: Final = 24
#: How many simulated minutes one request may move time forward, and so how many steps a plan can
#: hold: that many control steps, with a pause before them and a play after them.
MAX_MINUTES: Final = 10
MAX_PLAN_STEPS: Final = MAX_MINUTES + 2


def action_bound_seconds(client: ModelClient) -> float:
    """The longest the model calls of one action request can take on ``client``."""
    return sum(count * client.worst_case_seconds(role) for role, count in ACTION_PATH_CALLS)


class ActionKind(StrEnum):
    """What an utterance asks for. There is no sixth answer."""

    QUESTION = "question"
    APPEARANCE = "appearance"
    WORLD_EDIT = "world_edit"
    SIMULATION = "simulation"
    CAPABILITIES = "capabilities"


class WorldEditOperation(StrEnum):
    """The world edits this matrix prepares, and ``other`` for one it cannot express."""

    PLACE_OBJECT = "place_object"
    MOVE_OBJECT = "move_object"
    REMOVE_OBJECT = "remove_object"
    UNDO_LAST_EDIT = "undo_last_edit"
    PLACE_ARRANGEMENT = "place_arrangement"
    PLACE_THING = "place_thing"
    DIRECT_THING = "direct_thing"
    REQUEST_PIECES = "request_pieces"
    CHOOSE_MIND = "choose_mind"
    MOVE_THING = "move_thing"
    REMOVE_THING = "remove_thing"
    PLAY_BEING = "play_being"
    GIVE_BACK = "give_back"
    SET_MINDS_BUDGET = "set_minds_budget"
    OTHER = "other"


#: The operations the world-edit drafter's form offers, in the drafter's words: the matrix's own,
#: but a direct step is named by what it asks (``send_to`` a place, ``use`` it, or one of the hands
#: acts by its own name), each read back as one ``direct_thing`` with its act.
DRAFT_OPERATIONS: Final = (
    "place_object",
    "move_object",
    "remove_object",
    "undo_last_edit",
    "place_arrangement",
    "place_thing",
    "send_to",
    "use",
    *action_things.HANDS_ACTS,
    "request_pieces",
    "choose_mind",
    "play_being",
    "give_back",
    "set_minds_budget",
    "other",
)
#: A drafted direct step's operation and the act its typed action states.
_DRAFT_ACTS: Final = {"send_to": "go_to", "use": "use"}
#: The hands acts, drafted and typed by their own names.
_HANDS: Final = frozenset(action_things.HANDS_ACTS)


class SimulationAction(StrEnum):
    """What a simulation request asks of the world's time and people, and ``other`` for the rest."""

    PLAY = "play"
    PAUSE = "pause"
    SET_SPEED = "set_speed"
    ADVANCE = "advance"
    BRING_PEOPLE = "bring_people"
    SEND_AWAY = "send_away"
    BRING_BACK = "bring_back"
    TAKE_IN = "take_in"
    OTHER = "other"


#: Every code a plan's ``refusal`` can carry. Stable: codes are added, never renamed. Appearance
#: refusals carry the appearance path's own codes (``exulanica.selection.proposal.RefusalCode``).
ACTION_REFUSALS: Final = frozenset(
    {
        "stale_version",
        "action_not_offered",
        "action_unsupported",
        "action_unavailable",
        "action_not_permitted",
        "not_in_catalogue",
        "not_understood",
        "not_drafted",
        "preview_blocked",
        "no_change",
    }
)

#: Every code a plan's ``clarification`` can carry.
CLARIFICATIONS: Final = frozenset(
    {
        "asset_ambiguous",
        "object_ambiguous",
        "object_required",
        "arrangement_ambiguous",
        "origin_role_required",
        "placement_required",
        "viewer_required",
        "speed_required",
        "minutes_required",
        "region_required",
        # A thing to add, and what it goes beside; a being to ask, and the place.
        "kind_ambiguous",
        "anchor_ambiguous",
        "being_required",
        "being_ambiguous",
        "place_required",
        "place_ambiguous",
        # The thing a being is asked to pick up, put down, give or take.
        "thing_ambiguous",
        # Who a mind is chosen for (a being or a group) and which mind; and a choice that would
        # run more beings by models than the world's contract allows, with what fits.
        "whom_required",
        "whom_ambiguous",
        "mind_required",
        "mind_ambiguous",
        "too_many_people_for_models",
        # A budget for the world's minds: no figure the words state, two amounts of one kind,
        # or an amount over a span that is not an hour (never converted).
        "budget_required",
        "budget_ambiguous",
        "budget_period",
    }
)

# -- the matrix: each prepared operation and the routes it is sent to ---------------------------

_VERSION: Final = "/world/versions/{version_id}"
PLACE: Final = f"POST {_VERSION}/compositions/apply"
PLACE_PREVIEW: Final = f"POST {_VERSION}/compositions/preview"
MOVE: Final = f"POST {_VERSION}/objects/{{object_id}}/move"
MOVE_PREVIEW: Final = f"POST {_VERSION}/objects/{{object_id}}/move/preview"
REMOVE: Final = f"POST {_VERSION}/objects/{{object_id}}/remove"
REMOVE_PREVIEW: Final = f"POST {_VERSION}/objects/{{object_id}}/remove/preview"
UNDO: Final = f"POST {_VERSION}/objects/undo"
UNDO_PREVIEW: Final = f"POST {_VERSION}/objects/undo/preview"
ARRANGE: Final = f"POST {_VERSION}/arrangements/apply"
ARRANGE_PREVIEW: Final = f"POST {_VERSION}/arrangements/preview"
#: A thing placed by its kind, the route that takes its placing back, and a being's direct request.
THING_PLACE: Final = action_things.THING_PLACE
THING_UNDO: Final = f"POST {_VERSION}/things/undo"
#: A placed thing moved to another pose in its region, or taken out of the world.
THING_MOVE: Final = f"POST {_VERSION}/things/{{thing_id}}/move"
THING_REMOVE: Final = f"POST {_VERSION}/things/{{thing_id}}/remove"
DIRECT: Final = action_things.DIRECT
#: The playback controls a simulation plan's steps are sent to, and the creation of its people.
CONTROL: Final = f"PUT {_VERSION}/society/control"
CONTROL_STEP: Final = f"POST {_VERSION}/society/control/steps"
BRING_PEOPLE: Final = f"POST {_VERSION}/society"
#: Everyone sent away, or the same people brought back: one recorded minute.
PRESENCE: Final = f"POST {_VERSION}/society/presence"
#: A person playing one being of a society of things, and giving it back.
PLAY: Final = f"POST {_VERSION}/society/play"
PLAY_GIVE_BACK: Final = f"POST {_VERSION}/society/play/{{subject_id}}/give-back"
#: A living town's people taking in what was placed after they came: their society is made again
#: as a society of things, the same people under the same ids, and their day starts again.
TAKE_IN: Final = f"POST {_VERSION}/society/take-in"
#: What that erases and what it keeps, as codes the page has words for; the step states both
#: before the one yes, whole. The route gives no way back.
TAKE_IN_LOSES: Final = (
    "day_so_far",
    "clock_position",
    "playing_and_speed",
    "models_chosen",
    "looks_saved_for_residents",
    "comparisons_and_experiments",
    "companion_answers",
)
TAKE_IN_KEEPS: Final = (
    "people_homes_jobs_roles_shifts",
    "world",
    "things_placed",
    "door_grants_and_programs",
    "world_look",
)
#: Where every base a simulation step sends is read from: the version's clock.
CLOCK_READ: Final = f"GET {_VERSION}/clock"


#: The route a request for new pieces of a world's look is sent to: world-scoped, so no version
#: descriptor states it, and the plan states its own from the caller's grant (:func:`_with_pieces`).
PIECES: Final = "POST /world/piece-requests"


#: The route a choice of who decides is sent to, and what the actions route hands the planner for
#: it (:mod:`exulanica.selection.action_minds`).
MIND: Final = action_minds.MIND
Minds = action_minds.Minds
#: The route a world's budget for its minds is sent to. The budget is the world's and no
#: version's, so no version descriptor states it and the plan states its own (:func:`_with_budget`).
BUDGET: Final = action_budget.BUDGET


class Play(Protocol):
    """Playing a being, as the actions route hands it to the planner
    (``exulanica.api.mind_offer.WorldMinds``): what starting to play ``subject`` would meet now
    (``code``, ``playing``, ``played`` and ``choice_seq``), read with no lock and recording
    nothing; with no subject, only whom the caller plays."""

    def play_preview(self, subject: str | None) -> Mapping[str, Any]: ...


class Pieces(Protocol):
    """New pieces for one world, as the actions route hands them to the planner, which names the
    kinds (key, version and label each) and is answered with the request, its estimate and what the
    sheet names, or the code that blocks it (``exulanica.generation.offer.WorldPieces``)."""

    def available(self) -> bool: ...

    def offer(
        self, kinds: Sequence[tuple[str, int, str]], *, named: bool, idempotency_key: uuid.UUID
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class _Row:
    commit: str
    #: The route that previews the request, or None for one with no preview route: its own pure
    #: checks run in process instead (:mod:`exulanica.selection.action_things`).
    preview: str | None
    #: Where a later edit's base comes from and what replaying the request does.
    replay: str
    receipt: str
    compensation: str | None
    atomic: bool = False


_STALE: Final = "stale_base_refused"
_MATRIX: Final[Mapping[WorldEditOperation, _Row]] = {
    WorldEditOperation.PLACE_OBJECT: _Row(PLACE, PLACE_PREVIEW, _STALE, "version_edit", UNDO),
    WorldEditOperation.MOVE_OBJECT: _Row(MOVE, MOVE_PREVIEW, _STALE, "version_edit", UNDO),
    WorldEditOperation.REMOVE_OBJECT: _Row(REMOVE, REMOVE_PREVIEW, _STALE, "version_edit", UNDO),
    WorldEditOperation.UNDO_LAST_EDIT: _Row(UNDO, UNDO_PREVIEW, _STALE, "version_edit", None),
    WorldEditOperation.PLACE_ARRANGEMENT: _Row(
        ARRANGE, ARRANGE_PREVIEW, _STALE, "version_edits", UNDO, atomic=True
    ),
    WorldEditOperation.PLACE_THING: _Row(THING_PLACE, None, _STALE, "version_edit", THING_UNDO),
    # Sent again with its key it answers the request already recorded; a later minute is another
    # request, prepared again.
    WorldEditOperation.DIRECT_THING: _Row(
        DIRECT, None, "same_key_returns_the_recorded_request", "society_action_request", None
    ),
    # Sent again with its key it answers the requests its first answer held. Its route is
    # world-scoped: the plan states its descriptor (:func:`_with_pieces`).
    WorldEditOperation.REQUEST_PIECES: _Row(
        PIECES, None, "same_key_returns_the_recorded_request", "piece_requests", None
    ),
    # Sent again with its key it answers the choice already recorded. Taking a mind back is
    # another choice, of the routine, so nothing compensates it.
    WorldEditOperation.CHOOSE_MIND: _Row(
        MIND, None, "same_key_returns_the_recorded_choice", "model_choice", None
    ),
    WorldEditOperation.MOVE_THING: _Row(THING_MOVE, None, _STALE, "version_edit", THING_UNDO),
    WorldEditOperation.REMOVE_THING: _Row(THING_REMOVE, None, _STALE, "version_edit", THING_UNDO),
    # Playing is a choice naming the person: sent again by the one who plays, it answers the play
    # that stands; giving it back is what ends it.
    WorldEditOperation.PLAY_BEING: _Row(
        PLAY, None, "the_play_that_stands_is_returned", "model_choice", PLAY_GIVE_BACK
    ),
    WorldEditOperation.GIVE_BACK: _Row(
        PLAY_GIVE_BACK, None, "same_key_returns_the_recorded_choice", "model_choice", None
    ),
    # Sent again with its key it answers the budget that request recorded. A budget is put back
    # by setting the figures it had, which is another request, so nothing compensates it.
    WorldEditOperation.SET_MINDS_BUDGET: _Row(
        BUDGET, None, "same_key_returns_the_recorded_budget", "minds_budget", None
    ),
}

#: The style lifecycle's routes an appearance plan names: world-scoped, so no version descriptor
#: states them, and the caller's grant is read for them through :data:`Grant`.
STYLE_PREVIEW: Final = "POST /world/styles/previews"
STYLE_APPLY: Final = "POST /world/styles/previews/{preview_id}/apply"
STYLE_DISCARD: Final = "DELETE /world/styles/previews/{preview_id}"

#: A repository for one preview route, or None when the caller may not use that route. The route
#: opens it only after the caller's grant satisfies that preview route's permission, inside a
#: read-only transaction (``exulanica.api.routes.selection_actions``).
Previewer = Callable[[str], AbstractContextManager[WorldObjectRepository | None]]
#: For one route key, the permissions its declaration requires and whether the caller holds them,
#: read by the route from the one permission table (``exulanica.api.permissions``).
Grant = Callable[[str], tuple[list[str], bool]]
#: The version's clock read (``exulanica.world-clock/v1``), as ``GET .../clock`` answers it. The
#: route reads it only when a plan needs it, on the connection it plans with.
ClockReader = Callable[[], Mapping[str, Any]]
#: What a direct request made now would be made against: the society, the input its state
#: consumed, the newest input's sequence and the beings already asked at this minute, as the
#: actions route reads them (``SocietyActionRepository.request_context``), or None for a version
#: whose society takes none.
SocietyReader = Callable[
    [], tuple[Mapping[str, Any], Mapping[str, Any], int, frozenset[str]] | None
]
