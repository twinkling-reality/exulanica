"""The contract a model answers under when it runs a person in a world: the person role's code.

A person in a purposeful society chooses what to do next at the planner's own choice point: when
nothing is under way for them. For a person whose world's owner chose a model to run them, the
host asks that model at that point instead of leaving the choice to the routine. The person is the
first decision role (:mod:`exulanica.world.decision_roles`): its registry entry states its
catalogs, profiles and prompt texts as data, its adapter (:mod:`exulanica.world.roles.person`)
binds this module to the generic decision path, and this module states what only a person's
decisions need, from the society catalogs: what the model is shown, what it may answer and how the
answer is checked:

*   **What the person sees** is a context of the profile the role's entry names: the minute, how
    tired they are against the routine's own rest threshold, what they are doing and where they
    last were, and each option. Nothing in it is anybody's name, and no account holder's text:
    an option is read from the action catalog's words, the routine catalog's words for an
    activity, a walking distance and, for somebody to talk with, the number their simulated name
    ends with.
*   **What they may do** is what the action catalog of the request's contract states, and only
    what the routine itself could start for them in that minute, by the routine's own rules: go to
    a place that has room for them, for what the routine says is done there; wait a minute; and,
    where the contract and the input's routine both have them, stand a while at an open spot near
    them, or stop to talk with somebody the routine could pair them with. The model replaces the
    routine's draws and its preference that a tired person rests first, never its rules of what
    can be done. Each option is labelled by what it is, never by its position, and the options
    are shuffled by a seed of the society, the person and the minute, which the request records
    with the order, because the order a model reads its options in moves its choice.
*   **How the answer is asked for** is one choice among those labels, by the first mechanism the
    chosen model's manifest entry names as verified: in the answering order its entry states,
    where a measurement gave it one and the contract's version asks in it, and otherwise in the
    policy's order. The tool or schema is built by the generic path from the role's own
    description and these labels, and nowhere else.
*   **How it is checked**: the answer must be one of the labels; the engine then applies it only
    if it still holds when the minute runs (:func:`recheck_option`, :func:`recheck_talk`), and
    promises before the minute what it takes, a place, a spot to stand at or the two spots of a
    conversation, as a direct request's place is promised, so nobody choosing for themselves in
    that minute takes it.

What it does not do: say anything about another person but the number their simulated name ends
with and how far the walk to them is, or let a model decide for anybody but the person it runs: a
conversation it chooses happens only with somebody nobody, their own model included, decided for
in that minute.

Every option is built from the input the minute reads, whose walking graph and the spots nobody
stands at depend on that input alone. A run of minutes over frozen inputs builds each once per
input while :func:`input_memo` holds (a comparison's run and its replay do), keyed by the identity
of the input's own navigation and targets and dropped when the run ends; anywhere else each is
built where it is read, as before.
"""

from __future__ import annotations

import random
from collections import OrderedDict
from collections.abc import Callable, Container, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Final

from exulanica.models.choice import ChoiceRequest
from exulanica.models.manifest import AnsweringMechanism
from exulanica.world.decision_roles import (
    FEWEST_OPTIONS,
    GENERIC_REASONS,
    ContractError,
    DecisionContract,
    DecisionRole,
)
from exulanica.world.role_decisions import context_bytes, written_messages
from exulanica.world.society_catalogs import PurposefulActivity, PurposefulRoutine
from exulanica.world.society_planner import (
    PLACE_INPUTS,
    _free_place,
    _graph,
    _location_valid,
    _paths,
    drawn_stand_spot,
    free_to_talk,
    held_nodes,
    need_this_minute,
    routine_of,
    same_destination,
    stand_spots,
    standing_exclusions,
    standing_to_talk,
    talk_span,
    talk_spots,
    within_talk_reach,
)

__all__ = [
    "ACTION_FIELDS",
    "DECISION_REASONS",
    "FEWEST_OPTIONS",
    "PERSON_REASONS",
    "ContractError",
    "DecisionContract",
    "DecisionOption",
    "TalkPromise",
    "at_choice_point",
    "choice_options",
    "choice_request",
    "context_bytes",
    "decision_context",
    "decision_contract",
    "decision_messages",
    "input_memo",
    "observed_context",
    "option_goal_policy",
    "person_role",
    "places_to_stand",
    "recheck_option",
    "recheck_talk",
    "situation",
]

#: How a goal policy says a model chose it, so the planner records the model's own reason code
#: (``chosen_by_their_model``), never the one a person's own request gives.
CHOSEN_BY_MODEL: Final = "model"
#: The reasons only a person's decisions record, beside the generic path's own
#: (:data:`~exulanica.world.decision_roles.GENERIC_REASONS`), all of them when the minute consumes a
#: receipt.
PERSON_REASONS: Final = frozenset(
    {
        "person_asked_directly",
        "action_in_progress",
        "input_unavailable",
        "target_disabled_or_removed",
        "current_position_invalidated",
        "known_target_unreachable",
        "place_taken_this_minute",
        # When the minute consumes a choice to stand or to talk.
        "no_room_to_stand",
        "no_room_to_talk",
        # The person it chose to talk with was decided for in that minute, by their own model or
        # the world's owner, or was already stopping to talk with somebody else.
        "partner_busy",
        # The person it chose to talk with could not stop to talk by the routine's rule: not in the
        # society, not free to choose or standing, or out of the talk's reach.
        "partner_not_free",
    }
)
#: Every reason a person's decision receipt, or the minute that consumed it, records, by code. The
#: words catalog has words for exactly these (its ``decision_reason`` entries, which the page reads
#: as ``DECISION_WORDS``), held to this set by tests/test_companion_decision_model.py and
#: society-models-words-parity.test.ts.
DECISION_REASONS: Final = GENERIC_REASONS | PERSON_REASONS
#: Each action kind a person may be offered, with the placeholders its words may name, each filled
#: here from the catalog, the walk and, for somebody to talk with, the number their simulated name
#: ends with. The action catalog of each contract version states the kinds it offers among these.
ACTION_FIELDS: Final = {
    "target": frozenset({"activity", "metres"}),
    "wait": frozenset(),
    "stand": frozenset(),
    "talk": frozenset({"number", "metres"}),
}
#: What every recorded option states; one to talk with also states who, as ``partner_id``, so an
#: option of the first contract records exactly the bytes it always did.
_OPTION_FIELDS: Final = frozenset({"label", "kind", "action", "target_id", "activity", "walk_mm"})


def person_role() -> DecisionRole:
    """The person role, as the production registry states it: its catalogs, profiles and prompt
    texts. Read when first asked for, since the registry imports the person's adapter, which
    imports this module."""
    from exulanica.world.roles.person import person_role as registered

    return registered()


def __getattr__(name: str) -> Any:
    """``PROMPT_VERSION``: the person role's prompt version, as its registry entry states it. The
    comparison modules read it here until a comparison names the role it asks."""
    if name == "PROMPT_VERSION":
        return person_role().prompt_version
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def decision_contract(versions: Mapping[str, int] | None = None) -> DecisionContract:
    """The person role's contract of these catalog versions; left out, the one a new request
    records."""
    return person_role().contract(versions)


@dataclass(frozen=True, slots=True)
class DecisionOption:
    """One thing a person may be asked to do, as a request records it and a model reads it."""

    label: str
    kind: str
    action: str
    target_id: str | None
    activity: str | None
    walk_mm: int | None
    #: Who a conversation is with, by the society's identity for them; None for any other kind.
    partner_id: str | None = None

    def as_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "label": self.label,
            "kind": self.kind,
            "action": self.action,
            "target_id": self.target_id,
            "activity": self.activity,
            "walk_mm": self.walk_mm,
        }
        if self.kind == "talk":
            record["partner_id"] = self.partner_id
        return record

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> DecisionOption:
        talk = record.get("kind") == "talk"
        if set(record) != (_OPTION_FIELDS | {"partner_id"} if talk else _OPTION_FIELDS):
            raise ValueError("a recorded decision option states exactly its fields")
        if talk and not (isinstance(record["partner_id"], str) and record["partner_id"]):
            raise ValueError("a recorded conversation names who it is with")
        return cls(
            label=str(record["label"]),
            kind=str(record["kind"]),
            action=str(record["action"]),
            target_id=record["target_id"],
            activity=record["activity"],
            walk_mm=record["walk_mm"],
            partner_id=record["partner_id"] if talk else None,
        )


@dataclass(frozen=True, slots=True)
class TalkPromise:
    """A conversation a model chose, held before its minute as the routine's own pairing is: who
    it is with, where each of the two stands and how long it lasts."""

    partner_id: str
    node_id: str
    partner_node_id: str
    duration_ticks: int

    def mirrored(self, subject_id: str) -> TalkPromise:
        """The same conversation as the other person holds it: with ``subject_id``."""
        return TalkPromise(
            partner_id=subject_id,
            node_id=self.partner_node_id,
            partner_node_id=self.node_id,
            duration_ticks=self.duration_ticks,
        )


def at_choice_point(person: Mapping[str, Any]) -> bool:
    """Whether the routine itself chooses for this person in the coming minute.

    The planner's own choice point: no goal, or the action it completed. A person blocked on the
    way to a goal keeps the goal, as the planner keeps it for them, and is not asked.
    """
    return person["goal"] is None or person["action"]["status"] == "completed"


def _person(state: Mapping[str, Any], subject_id: str) -> dict[str, Any]:
    person = next((p for p in state["inhabitants"] if p["id"] == subject_id), None)
    if person is None:
        raise ValueError("the subject is not one of this society's people")
    return person


def _available(document: Mapping[str, Any]) -> bool:
    return (
        document["availability"] == "available" and not document["navigation"]["unavailable_reason"]
    )


def _activity_label(routine: PurposefulRoutine, target: Mapping[str, Any]) -> tuple[str, str]:
    """The routine entry a target's stay is read under, and the words it reads as."""
    key = target.get("activity")
    if isinstance(key, str) and key in routine.activities:
        activity = routine.activities[key]
    else:
        activity = routine.default(str(target["affordance"]))
    return activity.key, activity.label


class _InputMemo:
    """What options are built from that depends on one input alone, built once per input object:
    at most ``most`` inputs at a time, the one least recently read dropped first. An input is
    known by its navigation and targets objects themselves, held here, so an object freed and its
    identity reused is never taken for the input it replaced."""

    def __init__(self, most: int) -> None:
        self.most = most
        self._held: OrderedDict[tuple[int, int], tuple[Any, Any, dict[str, Any]]] = OrderedDict()

    def value(self, document: Mapping[str, Any], name: str, build: Callable[[], Any]) -> Any:
        navigation, targets = document["navigation"], document["targets"]
        key = (id(navigation), id(targets))
        held = self._held.get(key)
        if held is None or held[0] is not navigation or held[1] is not targets:
            held = (navigation, targets, {})
            self._held[key] = held
            while len(self._held) > self.most:
                self._held.popitem(last=False)
        self._held.move_to_end(key)
        values = held[2]
        if name not in values:
            values[name] = build()
        return values[name]


_MEMO: ContextVar[_InputMemo | None] = ContextVar("society_decision_input_memo", default=None)


@contextmanager
def input_memo(inputs: int) -> Iterator[None]:
    """While the block runs, build each of at most ``inputs`` inputs' walking graph and standing
    exclusions once, for this context alone: a run of minutes over frozen inputs, whose options
    read the same input every minute. Nothing is kept after the block."""
    token = _MEMO.set(_InputMemo(max(1, inputs)))
    try:
        yield
    finally:
        _MEMO.reset(token)


def _input_graph(document: Mapping[str, Any]) -> tuple[dict, dict, dict]:
    """The input's walking graph, as the planner reads it (read, never changed, by its callers)."""
    memo = _MEMO.get()
    if memo is None:
        return _graph(dict(document))
    return memo.value(document, "graph", lambda: _graph(dict(document)))


def _crowded(document: Mapping[str, Any]) -> frozenset[str]:
    """The nodes nobody waits or starts at in the input (:func:`standing_exclusions`)."""
    memo = _MEMO.get()
    if memo is None:
        return standing_exclusions(dict(document))
    return memo.value(document, "crowded", lambda: standing_exclusions(dict(document)))


def _reachable(
    state: Mapping[str, Any], document: Mapping[str, Any], person: dict[str, Any]
) -> tuple[dict, dict, set[str], str | None]:
    """The person's walking distances, the nodes others hold, and the node they stand at.

    ``person`` is the state's own record of them: the planner leaves out of what is held exactly
    that record, so where they stand and are headed stays theirs, as it does in the minute.
    """
    nodes, adjacent, edges = _input_graph(document)
    location = person["location"]
    start = location["node_id"] if location["edge"] is None else location["edge"]["to_node_id"]
    paths = _paths(start, adjacent)
    held = held_nodes(list(state["inhabitants"]), person, graph=(nodes, edges))
    here = location["node_id"] if location["edge"] is None else None
    return nodes, paths, held, here


def _off_place(
    routine: PurposefulRoutine, document: Mapping[str, Any], setting: str
) -> PurposefulActivity | None:
    """The routine's activity at no place in ``setting`` (``open`` standing, ``pair`` talking),
    where the input states places and the routine draws its choices, as the planner reads it."""
    if document["profile"] not in PLACE_INPUTS or routine.choice != "drawn":
        return None
    return routine.in_setting(setting)


def _paths_from(adjacent: Mapping[str, Any]) -> Any:
    """Walking distances from a node, each start walked once."""
    walked: dict[str, dict] = {}

    def paths_of(start: str) -> dict:
        if start not in walked:
            walked[start] = _paths(start, dict(adjacent))
        return walked[start]

    return paths_of


def _partners(
    state: Mapping[str, Any],
    document: Mapping[str, Any],
    person: dict[str, Any],
    routine: PurposefulRoutine,
    paths: Mapping[str, Any],
) -> list[tuple[int, dict[str, Any]]]:
    """Everybody the routine could pair this person with to talk now, and the walk to each.

    By the routine's own rules (``exulanica.world.society_planner``): somebody free to choose or
    standing, within the talk's reach, with two open spots beside each other both can walk to. The
    person themself stands on a node, as anybody who starts a talk does. Before the minute nobody
    is decided for yet, so no policy is read; the minute's own are when it runs
    (:func:`recheck_talk`).
    """
    talk = _off_place(routine, document, "pair")
    if talk is None or person["location"]["edge"] is not None:
        return []
    graph = _input_graph(document)
    crowded = _crowded(document)
    paths_of = _paths_from(graph[1])
    people = list(state["inhabitants"])
    found = []
    for other in people:
        if other is person or other["location"]["node_id"] not in paths:
            continue
        standing = standing_to_talk(other, routine, graph, ())
        if not (standing or free_to_talk(other, routine, graph, (), need=need_this_minute(other))):
            continue
        if not within_talk_reach(person, other, talk):
            continue
        if talk_spots(
            person, other, people, graph, crowded, set(), paths_of, talk, standing=standing
        ):
            found.append((paths[other["location"]["node_id"]][0], other))
    return found


def choice_options(
    state: Mapping[str, Any],
    document: Mapping[str, Any],
    subject_id: str,
    contract: DecisionContract,
    *,
    seed: str,
) -> tuple[DecisionOption, ...]:
    """What this person may be asked to do in the coming minute, in the order a model reads it.

    Empty when the planner would not let them choose, when the input cannot be walked, or when
    there is nothing to do but wait: such a person is left to the routine. Every enabled place
    they can reach that has a free place for them, as the planner itself finds room; where the
    contract states them and the input's routine has them, everybody the routine could pair them
    with to talk, and standing a while when an open spot lies within the routine's reach; the
    nearest places and people by the walk, ``options_maximum`` in all with standing and waiting,
    when there are more; then waiting, and the whole shuffled by the society's seed, the person
    and the minute. Under the first contract, which states places and waiting alone, this is the
    nearest ``options_maximum`` less one places, then waiting, as it always was.
    """
    person = _person(state, subject_id)
    if not at_choice_point(person) or not _available(document):
        return ()
    nodes, paths, held, here = _reachable(state, document, person)
    if not _location_valid(dict(person), nodes, _input_graph(document)[2]):
        return ()
    routine = routine_of(dict(document))
    places = document["profile"] in PLACE_INPUTS
    standing_at = None
    if places and here is not None:
        standing_at = next(
            (t["target_id"] for t in document["targets"] if here in t["place_node_ids"]), None
        )
    found = []
    for target in document["targets"]:
        if not target["enabled"] or target["node_id"] not in paths:
            continue
        if places and (
            target["target_id"] == standing_at or _free_place(target, paths, held, here) is None
        ):
            continue
        found.append((paths[target["node_id"]][0], target["target_id"], target))
    partners = (
        _partners(state, document, person, routine, paths) if "talk" in contract.words else []
    )
    stand = _off_place(routine, document, "open") if "stand" in contract.words else None
    if stand is not None and not places_to_stand(state, document, subject_id):
        stand = None
    # Places and people by the walk to each, a place before a person at the same walk, then by id.
    nearest = sorted(
        [(walk, 0, target_id, target) for walk, target_id, target in found]
        + [(walk, 1, other["id"], other) for walk, other in partners],
        key=lambda row: row[:3],
    )[: contract.value("options_maximum") - 1 - (stand is not None)]
    kept = [(walk, key, entry) for walk, kind, key, entry in nearest if kind == 0]
    near = [(walk, entry) for walk, kind, _key, entry in nearest if kind == 1]
    if not kept and not near and stand is None:
        return ()
    options: list[DecisionOption] = []
    labels: dict[str, int] = {}
    for walk, target_id, target in sorted(kept, key=lambda row: (row[1], row[0])):
        activity, words = _activity_label(routine, target)
        label = contract.words["target"].format(activity=words, metres=round(walk / 1000))
        labels[label] = labels.get(label, 0) + 1
        if labels[label] > 1:
            label = f"{label} ({labels[label]})"
        options.append(
            DecisionOption(
                label=label,
                kind="target",
                action=contract.action_keys["target"],
                target_id=target_id,
                activity=activity,
                walk_mm=walk,
            )
        )
    talk = _off_place(routine, document, "pair")
    for walk, other in sorted(near, key=lambda row: row[1]["ordinal"]):
        options.append(
            DecisionOption(
                # The number their simulated name ends with: theirs for the society's life.
                label=contract.words["talk"].format(
                    number=other["ordinal"] + 1, metres=round(walk / 1000)
                ),
                kind="talk",
                action=contract.action_keys["talk"],
                target_id=None,
                activity=None if talk is None else talk.key,
                walk_mm=walk,
                partner_id=other["id"],
            )
        )
    if stand is not None:
        options.append(
            DecisionOption(
                label=contract.words["stand"],
                kind="stand",
                action=contract.action_keys["stand"],
                target_id=None,
                activity=stand.key,
                walk_mm=None,
            )
        )
    options.append(
        DecisionOption(
            label=contract.words["wait"],
            kind="wait",
            action=contract.action_keys["wait"],
            target_id=None,
            activity=None,
            walk_mm=None,
        )
    )
    random.Random(f"{seed}:{subject_id}:{state['tick']}").shuffle(options)
    return tuple(options)


def observed_context(
    state: Mapping[str, Any],
    document: Mapping[str, Any],
    subject_id: str,
    options: Sequence[DecisionOption],
    *,
    profile: str,
) -> dict[str, Any]:
    """What the person sees, as a request of ``profile`` records it: how they are, and their
    options in order."""
    person = _person(state, subject_id)
    routine = routine_of(dict(document))
    rest = [a.preferred_at_need for a in routine.activities.values() if a.preferred_at_need > 0]
    targets = {t["target_id"]: t for t in document["targets"]}
    last = targets.get(person.get("last_completed_target_id") or "")
    action = person["action"]
    return {
        "profile": profile,
        "subject_id": subject_id,
        "branch_id": state["branch_id"],
        "tick": state["tick"],
        "need_milli": person["need_milli"],
        "rest_at_need_milli": min(rest) if rest else None,
        "doing": {"kind": action["kind"], "status": action["status"], "reason": action["reason"]},
        "last_activity": None if last is None else _activity_label(routine, last)[1],
        "options": [option.as_record() for option in options],
    }


def decision_context(
    state: Mapping[str, Any],
    document: Mapping[str, Any],
    subject_id: str,
    options: Sequence[DecisionOption],
) -> dict[str, Any]:
    """What the person sees, under the context profile the person role's registry entry states."""
    return observed_context(
        state, document, subject_id, options, profile=person_role().context_profile
    )


def _doing(context: Mapping[str, Any]) -> str:
    doing = context["doing"]
    if doing["status"] == "completed":
        return "you have just finished what you were doing"
    if doing["status"] == "blocked":
        return "you are waiting"
    return "you have just arrived"


def situation(context: Mapping[str, Any]) -> list[str]:
    """The person's situation as a model reads it, before their options: the minute, what they
    just did, how tired they are against the routine's rest threshold and the last place used."""
    lines = [
        f"It is minute {context['tick']} in the world, and {_doing(context)}.",
        f"Tiredness: {context['need_milli']} of 1000."
        + (
            f" People here rest once it passes {context['rest_at_need_milli']}."
            if context["rest_at_need_milli"] is not None
            else ""
        ),
    ]
    if context["last_activity"] is not None:
        lines.append(f"The last place you used: {context['last_activity']}.")
    return lines


def decision_messages(
    context: Mapping[str, Any], mechanism: AnsweringMechanism
) -> list[dict[str, str]]:
    """The person role's instruction and the person's situation, as a model reads them."""
    return written_messages(person_role(), situation(context), context, mechanism)


def choice_request(context: Mapping[str, Any]) -> ChoiceRequest:
    """The one choice a model answers for a person, built from the options and nowhere else."""
    return person_role().choice(context)


def recheck_option(
    state: Mapping[str, Any],
    document: Mapping[str, Any],
    subject_id: str,
    option: DecisionOption,
    promised: set[str],
) -> tuple[str | None, str | None]:
    """Whether a chosen place, wait or stand still holds this minute, and what it is promised.

    ``(None, place)`` when it holds: the place at a target, ``None`` for waiting or an input that
    states no places, and for standing the spot the routine draws among the open ones as the
    minute begins; otherwise ``(reason, None)`` naming why it does not. ``promised`` holds every
    place and spot promised before this choice in the minute. A conversation is checked by
    :func:`recheck_talk`, which also reads who else is decided for.
    """
    person = _person(state, subject_id)
    if not at_choice_point(person):
        return "action_in_progress", None
    if option.kind == "wait":
        return None, None
    if not _available(document):
        return "input_unavailable", None
    if option.kind == "stand":
        return _recheck_stand(state, document, person, promised)
    if option.kind != "target":
        raise ValueError(f"a {option.kind!r} choice is not checked here")
    current = next((t for t in document["targets"] if t["target_id"] == option.target_id), None)
    if current is None or not current["enabled"]:
        return "target_disabled_or_removed", None
    nodes, paths, held, here = _reachable(state, document, person)
    if not _location_valid(dict(person), nodes, _input_graph(document)[2]):
        return "current_position_invalidated", None
    if current["node_id"] not in paths:
        return "known_target_unreachable", None
    if document["profile"] not in PLACE_INPUTS:
        return None, None
    place = _free_place(current, paths, held | promised, here)
    if place is None:
        return "place_taken_this_minute", None
    return None, place


def places_to_stand(
    state: Mapping[str, Any],
    document: Mapping[str, Any],
    subject_id: str,
    promised: Container[str] = frozenset(),
) -> list[str]:
    """Where this person may stand a while in the coming minute, as the routine lists it: the
    open nodes within its standing reach that they can walk to and nobody else stands at or is
    headed to, the one they stand at included, less any spot ``promised`` to a choice before; in
    node order, the list the routine's own draw picks from. Empty where the input's routine has
    nobody stand."""
    person = _person(state, subject_id)
    stand = _off_place(routine_of(dict(document)), document, "open")
    if stand is None:
        return []
    _nodes, paths, held, _here = _reachable(state, document, person)
    return [
        spot
        for spot in stand_spots(
            _input_graph(document),
            _crowded(document),
            held,
            dict(paths),
            person,
            stand,
        )
        if spot not in promised
    ]


def _recheck_stand(
    state: Mapping[str, Any],
    document: Mapping[str, Any],
    person: dict[str, Any],
    promised: set[str],
) -> tuple[str | None, str | None]:
    """Where a person who chose to stand a while stands, drawn as the routine draws it."""
    nodes, _paths, _held, _here = _reachable(state, document, person)
    if not _location_valid(dict(person), nodes, _input_graph(document)[2]):
        return "current_position_invalidated", None
    spots = places_to_stand(state, document, person["id"], promised)
    if not spots:
        return "no_room_to_stand", None
    # The minute the choice is applied in is the one after the state it was asked over.
    return None, drawn_stand_spot(state["seed_sha256"], state["tick"] + 1, person, spots)


def recheck_talk(
    state: Mapping[str, Any],
    document: Mapping[str, Any],
    subject_id: str,
    option: DecisionOption,
    promised: set[str],
    decided: Container[str],
) -> TalkPromise | str:
    """Whether a chosen conversation still holds this minute: how it is promised, or why not.

    ``decided`` holds everybody the minute has decided for so far: a direct request, a model's
    applied choice, or a conversation promised to somebody else. The other person must be free to
    choose or standing by the routine's rule and nobody decided for, within the talk's reach, with
    two open spots beside each other that nobody holds and nothing promised takes; the spots and
    the talk's length are the ones the routine's own pairing would give. The promise when it
    holds, otherwise the reason it does not.
    """
    person = _person(state, subject_id)
    if not at_choice_point(person):
        return "action_in_progress"
    if not _available(document):
        return "input_unavailable"
    graph = _input_graph(document)
    if person["location"]["edge"] is not None or not _location_valid(
        dict(person), graph[0], graph[2]
    ):
        return "current_position_invalidated"
    routine = routine_of(dict(document))
    talk = _off_place(routine, document, "pair")
    people = list(state["inhabitants"])
    partner = next((other for other in people if other["id"] == option.partner_id), None)
    if talk is None or partner is None or partner is person:
        return "partner_not_free"
    if partner["id"] in decided:
        return "partner_busy"
    standing = standing_to_talk(partner, routine, graph, decided)
    free = free_to_talk(partner, routine, graph, decided, need=need_this_minute(partner))
    if not (standing or free) or not within_talk_reach(person, partner, talk):
        return "partner_not_free"
    spots = talk_spots(
        person,
        partner,
        people,
        graph,
        _crowded(document),
        promised,
        _paths_from(graph[1]),
        talk,
        standing=standing,
    )
    if spots is None:
        return "no_room_to_talk"
    return TalkPromise(
        partner_id=partner["id"],
        node_id=spots[0],
        partner_node_id=spots[1],
        duration_ticks=talk_span(state["seed_sha256"], state["tick"] + 1, person, talk),
    )


def option_goal_policy(option: DecisionOption, promise: str | TalkPromise | None) -> dict[str, Any]:
    """The planner's goal policy for an applied choice: the existing seam, marked as a model's.

    ``promise`` is what the choice's check promised it: a place or a spot to stand at, a
    conversation, or nothing.
    """
    if option.kind == "wait":
        return {"allowed_target_ids": [], "wait": True}
    if option.kind == "stand" and isinstance(promise, str):
        return {
            "allowed_target_ids": [],
            "activity": option.activity,
            "place_node_id": promise,
            "chosen_by": CHOSEN_BY_MODEL,
        }
    if option.kind == "talk" and isinstance(promise, TalkPromise):
        return {
            "allowed_target_ids": [],
            "activity": option.activity,
            "partner_id": promise.partner_id,
            "place_node_id": promise.node_id,
            "partner_node_id": promise.partner_node_id,
            "duration_ticks": promise.duration_ticks,
            "chosen_by": CHOSEN_BY_MODEL,
        }
    if option.kind != "target" or isinstance(promise, TalkPromise):
        raise ValueError(f"no goal policy for a {option.kind!r} choice promised {promise!r}")
    policy: dict[str, Any] = {
        "allowed_target_ids": [option.target_id],
        "preferred_target_id": option.target_id,
        "chosen_by": CHOSEN_BY_MODEL,
    }
    if promise is not None:
        policy["place_node_id"] = promise
    return policy


def same_option_target(recorded: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    """Whether a target a request recorded is the place the current input states."""
    return same_destination(dict(recorded), dict(current))
