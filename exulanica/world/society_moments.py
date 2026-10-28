"""A world's moments: what its characters did that a person would tell, from its society's records.

A moment is formed by a versioned data rule (``society-moment-rules.v1.json``, profile
:data:`RULES_PROFILE`) from the events one simulated minute recorded: a line said to someone (the
first between two characters is a meeting), a line said to everyone near, a decision to go somewhere
or to leave, following someone, and handing a thing over. It is written in the same transaction as
that minute (:func:`record_moments`, called by the society repository as it commits the minute), so
a minute and its moments land together or not at all, and the same rule forms the moments of
minutes played before it existed (:func:`backfill`, through the replay).

A moment holds no words of anyone's: a line said is kept once, in its event, and
:func:`read_moments` joins it from there, so erasing a society's events erases its lines. It never
asks a model and never writes a sentence: it states kinds, ids, the world's own records and the
lines as said, and a page words them. Its ``scene`` records what a picture of it needs as the live
drawing reads it (each person's position, last path, action and partner), never a camera or a pose.

Moments are deleted only with their society (``society_erase_rows``).
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Protocol

from psycopg.types.json import Jsonb

from exulanica.world.society import SocietyEvent, society_state_sha256
from exulanica.world.society_decision_contract import POINT_KIND

__all__ = [
    "MOMENTS_PROFILE",
    "RULES_PROFILE",
    "Moment",
    "MomentRules",
    "backfill",
    "chosen_dids",
    "form_moments",
    "load_rules",
    "merge_moments",
    "moment_id_of",
    "option_did",
    "read_moments",
    "record_moments",
    "touched_spans",
]

RULES_PROFILE: Final = "exulanica.society-moment-rules/v1"
MOMENTS_PROFILE: Final = "exulanica.world-history-moments/v1"
#: What a walk to a spot the person playing chose did (the contract's point option): a going that
#: names no place, and that the moment rules give no branch kind of its own.
WENT_TO_SPOT: Final = "went_to_spot"
_RULES_PATH: Final = Path(__file__).with_name("society-moment-rules.v1.json")
#: The namespace a moment's id is derived in, from its version, its rule and the event it is
#: anchored on, so the minute's hook and a later back-fill name the same moment the same way.
_MOMENT_NAMESPACE: Final = uuid.uuid5(uuid.NAMESPACE_URL, "exulanica:society-moment")
#: The most moments one read answers.
READ_MOST: Final = 200
#: The moment kinds a line said makes.
_SPOKEN: Final = frozenset({"met", "spoke", "talked"})
#: Who decides a moment that is the world's story whoever is in it (H18): anyone but the routine.
_STORY_DECIDERS: Final = ("model", "person", "external")


@dataclass(frozen=True, slots=True)
class MomentRules:
    """The rule file, read and checked: what counts, in what order, and the figures it uses."""

    profile: str
    deciders: frozenset[str]
    any_decider_kinds: frozenset[str]
    order: tuple[str, ...]
    decision_kinds: Mapping[str, str]
    event_kinds: Mapping[str, str]
    branch_kinds: Mapping[str, str]
    exchange_minutes: int
    lines_most: int
    went_spacing_minutes: int
    merge_minutes: int
    place_radius_mm: int
    scene_radius_mm: int


def load_rules(path: Path | None = None) -> MomentRules:
    """The moment rule at ``path`` (the shipped v1 by default), refused when it is not one."""
    if path is None:
        return _shipped_rules()
    return _rules_from(json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def _shipped_rules() -> MomentRules:
    return _rules_from(json.loads(_RULES_PATH.read_text(encoding="utf-8")))


def _rules_from(document: Mapping[str, Any]) -> MomentRules:
    if document.get("profile") != RULES_PROFILE:
        raise ValueError(f"a moment rule names {RULES_PROFILE}")
    order = tuple(str(kind) for kind in document["order"])
    kinds = set(order)
    mapped = {**document["decision_kinds"], **document["event_kinds"]}
    if not set(mapped.values()) <= kinds or not {"met", "spoke", "spoke_to_all"} <= kinds:
        raise ValueError("every moment kind the rule makes is in its order")
    figures = {
        name: int(document[name])
        for name in (
            "exchange_minutes",
            "lines_most",
            "went_spacing_minutes",
            "merge_minutes",
            "place_radius_mm",
            "scene_radius_mm",
        )
    }
    if any(value < 1 for value in figures.values()):
        raise ValueError("a moment rule's figures are whole numbers of at least 1")
    return MomentRules(
        profile=RULES_PROFILE,
        deciders=frozenset(str(kind) for kind in document["deciders"]),
        any_decider_kinds=frozenset(str(kind) for kind in document["any_decider_kinds"]),
        order=order,
        decision_kinds={str(k): str(v) for k, v in document["decision_kinds"].items()},
        event_kinds={str(k): str(v) for k, v in document["event_kinds"].items()},
        branch_kinds={str(k): str(v) for k, v in document["branch_kinds"].items()},
        **figures,
    )


def moment_id_of(version_id: uuid.UUID, rules: MomentRules, anchor: uuid.UUID) -> uuid.UUID:
    """A moment's stable id: the same from the minute's hook and from a back-fill."""
    return uuid.uuid5(_MOMENT_NAMESPACE, f"{version_id}:{rules.profile}:{anchor}")


@dataclass(frozen=True, slots=True)
class Moment:
    """One moment as it is stored."""

    moment_id: uuid.UUID
    tick: int
    kind: str
    subjects: tuple[uuid.UUID, ...]
    anchor_event_id: uuid.UUID
    event_ids: tuple[uuid.UUID, ...]
    request_id: uuid.UUID | None
    decider: Mapping[str, Any]
    place: Mapping[str, Any] | None = None
    thing: str | None = None
    target: Mapping[str, Any] | None = None
    scene: Mapping[str, Any] = field(default_factory=dict)

    def document(self) -> dict[str, Any]:
        """What the row's ``document`` holds: who decided, where, the thing handed, the scene."""
        return {
            "decider": dict(self.decider),
            "place": None if self.place is None else dict(self.place),
            "thing": self.thing,
            "target": None if self.target is None else dict(self.target),
            "scene": dict(self.scene),
        }


class Known(Protocol):
    """What the moments already written for a society say, as forming the next minute's needs."""

    def met(self, first: uuid.UUID, second: uuid.UUID) -> bool: ...

    def last_went(self, subject: uuid.UUID) -> int | None: ...


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return None if value is None else uuid.UUID(str(value))
    except ValueError:
        return None


def _decisions_of(events: Iterable[SocietyEvent]) -> dict[uuid.UUID, dict[str, Any]]:
    """Who decided each subject's minute, from its applied decision:
    ``{kind, model, request_id}``."""
    found: dict[uuid.UUID, dict[str, Any]] = {}
    for event in events:
        if event.kind != "decision_applied" or event.document.get("disposition") != "applied":
            continue
        model = event.document.get("model")
        found[event.subject_id] = {
            "kind": str(event.document.get("origin") or "model"),
            "model": None if not isinstance(model, Mapping) else dict(model),
            "request_id": _uuid(event.document.get("request_id")),
        }
    return found


def _routine() -> dict[str, Any]:
    return {"kind": "routine", "model": None, "request_id": None}


def form_moments(
    rules: MomentRules,
    version_id: uuid.UUID,
    state: Mapping[str, Any],
    events: Sequence[SocietyEvent],
    known: Known,
    options: Mapping[uuid.UUID, Mapping[str, Any]],
) -> list[Moment]:
    """The moments one minute makes: ``events`` are the minute's, ``state`` the state after it,
    ``known`` the moments written before it, ``options`` each applied decision's option kind by its
    request. One moment at most per subject a minute, the first kind in the rule's order."""
    decided = _decisions_of(events)
    met_now: set[frozenset[uuid.UUID]] = set()
    candidates: list[tuple[int, Moment]] = []
    spoken: list[Moment] = []

    def met(first: uuid.UUID, second: uuid.UUID) -> bool:
        return frozenset((first, second)) in met_now or known.met(first, second)

    def add(
        kind: str,
        event: SocietyEvent,
        subjects: Sequence[uuid.UUID],
        decider: Mapping[str, Any],
        *,
        request_id: uuid.UUID | None = None,
        thing: str | None = None,
        target: Mapping[str, Any] | None = None,
    ) -> None:
        if decider["kind"] not in rules.deciders and kind not in rules.any_decider_kinds:
            return
        if kind not in rules.order:
            return
        candidates.append(
            (
                rules.order.index(kind),
                Moment(
                    moment_id=moment_id_of(version_id, rules, event.event_id),
                    tick=event.tick,
                    kind=kind,
                    subjects=tuple(subjects),
                    anchor_event_id=event.event_id,
                    event_ids=(event.event_id,),
                    request_id=request_id,
                    decider={"kind": decider["kind"], "model": decider.get("model")},
                    thing=thing,
                    target=target,
                ),
            )
        )

    for event in events:
        thing = event.document.get("thing")
        details: Mapping[str, Any] = thing if isinstance(thing, Mapping) else {}
        if event.kind == "said":
            to = _uuid(details.get("to"))
            model = details.get("model")
            decider = {
                "kind": str(details.get("decider") or "model"),
                "model": dict(model) if isinstance(model, Mapping) else None,
            }
            request_id = _uuid(details.get("request_id"))
            if to is None:
                add("spoke_to_all", event, (event.subject_id,), decider, request_id=request_id)
                continue
            kind = "spoke" if met(event.subject_id, to) else "met"
            if kind == "met":
                met_now.add(frozenset((event.subject_id, to)))
            before = len(candidates)
            add(kind, event, (event.subject_id, to), decider, request_id=request_id)
            spoken.extend(moment for _, moment in candidates[before:])
        elif event.kind == "social_contact" and event.document.get("outcome") == "talk_started":
            goal = event.document.get("goal")
            partner = _uuid(goal.get("partner_id")) if isinstance(goal, Mapping) else None
            if partner is not None and not met(event.subject_id, partner):
                met_now.add(frozenset((event.subject_id, partner)))
                decider = decided.get(event.subject_id, _routine())
                add(
                    "met",
                    event,
                    (event.subject_id, partner),
                    decider,
                    request_id=decider.get("request_id"),
                )
        elif event.kind == "decision_applied":
            decision = decided.get(event.subject_id)
            if decision is None or decision["request_id"] is None:
                continue
            option = options.get(decision["request_id"]) or {}
            kind = rules.decision_kinds.get(str(option.get("kind") or ""))
            if kind is None:
                continue
            if kind == "talked":
                # A decision to talk: a meeting the first time the two talk, then talking.
                partner = _uuid(option.get("partner_id") or option.get("addressee_id"))
                if partner is None:
                    continue
                kind = "talked" if met(event.subject_id, partner) else "met"
                if kind == "met":
                    met_now.add(frozenset((event.subject_id, partner)))
                add(
                    kind,
                    event,
                    (event.subject_id, partner),
                    decision,
                    request_id=decision["request_id"],
                )
                continue
            if kind == "went":
                last = known.last_went(event.subject_id)
                if last is not None and event.tick - last < rules.went_spacing_minutes:
                    continue
            target = (
                None
                if option.get("target_id") is None
                else {"target_id": str(option["target_id"]), "activity": option.get("activity")}
            )
            add(
                kind,
                event,
                (event.subject_id,),
                decision,
                request_id=decision["request_id"],
                target=target,
            )
        elif event.kind in rules.event_kinds:
            other = _uuid(details.get("with"))
            decision = decided.get(event.subject_id, _routine())
            add(
                rules.event_kinds[event.kind],
                event,
                (event.subject_id, *(() if other is None else (other,))),
                decision,
                request_id=decision.get("request_id"),
                thing=None if details.get("thing") is None else str(details["thing"]),
            )

    chosen: dict[uuid.UUID, tuple[int, Moment]] = {}
    for rank, moment in candidates:
        held = chosen.get(moment.subjects[0])
        if held is None or rank < held[0]:
            chosen[moment.subjects[0]] = (rank, moment)
    # A line said between the people of the moment kept for its speaker joins that moment's events,
    # so it is read with it: the engine's own meeting of the two comes first in a minute, and would
    # otherwise keep the minute without the words. Its anchor, kind and id stay the kept moment's.
    for line in spoken:
        rank, kept = chosen[line.subjects[0]]
        if kept is not line and set(kept.subjects) == set(line.subjects):
            joined = (*kept.event_ids, *line.event_ids)
            chosen[line.subjects[0]] = (
                rank,
                replace(
                    kept,
                    event_ids=joined,
                    request_id=kept.request_id or line.request_id,
                ),
            )
    kept = sorted((moment for _, moment in chosen.values()), key=lambda m: str(m.anchor_event_id))
    return [
        replace(
            moment,
            place=place_of(rules, state, moment.subjects[0]),
            scene=scene_of(rules, state, moment.subjects),
        )
        for moment in kept
    ]


def _people(state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    people = state.get("inhabitants")
    return [one for one in people if isinstance(one, Mapping)] if isinstance(people, list) else []


def _position(one: Mapping[str, Any]) -> tuple[float, float] | None:
    position = one.get("position_mm")
    if not isinstance(position, Sequence) or len(position) < 2:
        return None
    return float(position[0]), float(position[1])


def place_of(
    rules: MomentRules, state: Mapping[str, Any], subject: uuid.UUID
) -> dict[str, Any] | None:
    """Where a subject is, as the world records it: the nearest thing its author placed within the
    rule's radius (``{placed_id, thing_id}``, which a page names as build mode does), else none."""
    person = next((one for one in _people(state) if one.get("id") == str(subject)), None)
    here = None if person is None else _position(person)
    if here is None:
        return None
    nearest: tuple[float, Mapping[str, Any]] | None = None
    for thing in state.get("things") or ():
        if not isinstance(thing, Mapping) or thing.get("placed_id") is None:
            continue
        there = _position(thing)
        if there is None:
            continue
        distance = math.dist(here, there)
        if distance <= rules.place_radius_mm and (nearest is None or distance < nearest[0]):
            nearest = (distance, thing)
    if nearest is None:
        return None
    return {"placed_id": str(nearest[1]["placed_id"]), "thing_id": str(nearest[1].get("id"))}


def _scene_person(one: Mapping[str, Any]) -> dict[str, Any]:
    held_action, held_goal = one.get("action"), one.get("goal")
    action: Mapping[str, Any] = held_action if isinstance(held_action, Mapping) else {}
    goal: Mapping[str, Any] = held_goal if isinstance(held_goal, Mapping) else {}
    path = one.get("motion_path_mm")
    return {
        "id": str(one.get("id")),
        "position_mm": list(one.get("position_mm") or []),
        "path_mm": [list(point) for point in path[-2:]] if isinstance(path, list) else [],
        "action": {
            "kind": action.get("kind"),
            "target_id": action.get("target_id"),
            "activity": action.get("activity"),
        },
        "partner_id": goal.get("partner_id"),
    }


def scene_of(
    rules: MomentRules, state: Mapping[str, Any], subjects: Sequence[uuid.UUID]
) -> dict[str, Any]:
    """What a picture of the moment needs, as the live drawing reads it: the state's digest, the
    people catalog it was drawn from where the state names one, and the people in it (the subjects
    first, then everyone within the rule's radius of the first), never a camera or a pose."""
    people = _people(state)
    by_id = {str(one.get("id")): one for one in people}
    first = by_id.get(str(subjects[0])) if subjects else None
    centre = None if first is None else _position(first)
    named = [by_id[str(subject)] for subject in subjects if str(subject) in by_id]
    near = [
        one
        for one in people
        if str(one.get("id")) not in {str(subject) for subject in subjects}
        and centre is not None
        and (where := _position(one)) is not None
        and math.dist(centre, where) <= rules.scene_radius_mm
    ]
    near.sort(key=lambda one: str(one.get("id")))
    return {
        "state_sha256": society_state_sha256(dict(state)),
        "people_catalog_sha256": state.get("people_catalog_sha256"),
        "people": [_scene_person(one) for one in (*named, *near)],
    }


# -- writing ---------------------------------------------------------------------------------------


class _Stored:
    """The moments written for one society before minute ``before``, as :class:`Known` asks them.
    Bounded by the minute being formed, so a back-fill run after later minutes were played forms an
    earlier minute from what came before it, as the minute's own hook did."""

    def __init__(
        self, connection: Any, workspace_id: uuid.UUID, society_id: uuid.UUID, before: int
    ) -> None:
        self.connection, self.workspace_id, self.society_id = connection, workspace_id, society_id
        self.before = before

    def met(self, first: uuid.UUID, second: uuid.UUID) -> bool:
        row = self.connection.execute(
            "select 1 from world_society_moment where workspace_id=%s and society_id=%s "
            "and kind = any(%s) and subjects @> %s::uuid[] and tick < %s limit 1",
            (self.workspace_id, self.society_id, sorted(_SPOKEN), [first, second], self.before),
        ).fetchone()
        return row is not None

    def last_went(self, subject: uuid.UUID) -> int | None:
        row = self.connection.execute(
            "select max(tick) as tick from world_society_moment where workspace_id=%s "
            "and society_id=%s and kind='went' and subjects[1]=%s and tick < %s",
            (self.workspace_id, self.society_id, subject, self.before),
        ).fetchone()
        if row is None:
            return None
        value = row["tick"] if isinstance(row, Mapping) else row[0]
        return None if value is None else int(value)


def _options(
    connection: Any, workspace_id: uuid.UUID, society_id: uuid.UUID, events: Sequence[SocietyEvent]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Each applied decision's chosen option, read from its receipt."""
    requests = sorted(
        {
            request
            for event in events
            if event.kind == "decision_applied"
            and (request := _uuid(event.document.get("request_id"))) is not None
        },
        key=str,
    )
    if not requests:
        return {}
    rows = connection.execute(
        "select request_id, document->'proposal'->'option' as option "
        "from world_society_decision where workspace_id=%s and society_id=%s "
        "and request_id = any(%s)",
        (workspace_id, society_id, requests),
    ).fetchall()
    return {
        uuid.UUID(str(row["request_id"])): dict(row["option"])
        for row in rows
        if isinstance(row["option"], Mapping)
    }


def record_moments(
    connection: Any,
    workspace_id: uuid.UUID,
    row: Mapping[str, Any],
    state: Mapping[str, Any],
    events: Sequence[SocietyEvent],
    rules: MomentRules | None = None,
) -> list[Moment]:
    """Form and write the moments one minute makes, in the caller's transaction; a moment written
    before (a back-fill over played minutes) is left as it is. Answers the moments formed."""
    rules = load_rules() if rules is None else rules
    if not events:
        return []
    society_id = row["society_id"]
    moments = form_moments(
        rules,
        row["version_id"],
        state,
        events,
        _Stored(connection, workspace_id, society_id, min(event.tick for event in events)),
        _options(connection, workspace_id, society_id, events),
    )
    for moment in moments:
        document = moment.document()
        connection.execute(
            "insert into world_society_moment(workspace_id,moment_id,society_id,"
            "version_id,tick,kind,rule_version,anchor_event_id,event_ids,request_id,subjects,"
            "document,document_sha256) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (workspace_id, moment_id) do nothing",
            (
                workspace_id,
                moment.moment_id,
                society_id,
                row["version_id"],
                moment.tick,
                moment.kind,
                rules.profile,
                moment.anchor_event_id,
                list(moment.event_ids),
                moment.request_id,
                list(moment.subjects),
                Jsonb(document),
                society_state_sha256(document),
            ),
        )
    return moments


def backfill(
    replay: Callable[..., Any],
    connection: Any,
    workspace_id: uuid.UUID,
    row: Mapping[str, Any],
    version_id: uuid.UUID,
    rules: MomentRules | None = None,
) -> int:
    """Write the moments of every minute a society played before moments were written, through its
    replay (``replay(version_id, observe=...)``, which hands each verified minute's states and
    events). Moments already written are left as they are. Answers how many minutes were seen."""
    seen = 0

    def observe(_before: Mapping[str, Any], after: Mapping[str, Any], events: Any) -> None:
        nonlocal seen
        seen += 1
        record_moments(connection, workspace_id, row, after, tuple(events), rules)

    replay(version_id, observe=observe)
    return seen


# -- reading ---------------------------------------------------------------------------------------


def _lines(
    connection: Any,
    workspace_id: uuid.UUID,
    society_id: uuid.UUID,
    event_ids: list[uuid.UUID],
    name: Callable[[str], str | None],
) -> dict[uuid.UUID, dict[str, Any]]:
    """Each line said among ``event_ids``, as said, with who decided it."""
    if not event_ids:
        return {}
    rows = connection.execute(
        "select event_id, tick, subject_id, document->'thing' as thing from world_society_event "
        "where workspace_id=%s and society_id=%s and event_kind='said' and event_id = any(%s)",
        (workspace_id, society_id, event_ids),
    ).fetchall()
    found: dict[uuid.UUID, dict[str, Any]] = {}
    for one in rows:
        thing = one["thing"] if isinstance(one["thing"], Mapping) else {}
        to = thing.get("to")
        model = thing.get("model")
        request = _uuid(thing.get("request_id"))
        found[uuid.UUID(str(one["event_id"]))] = {
            "tick": int(one["tick"]),
            "by": str(one["subject_id"]),
            # The decision that said it, so a page can open it; none for a line no request asked.
            "request_id": None if request is None else str(request),
            "to": [] if to is None else [str(to)],
            "line": str(thing.get("line") or ""),
            "decider": {
                "kind": str(thing.get("decider") or "model"),
                "model": None
                if not isinstance(model, Mapping)
                else {**model, "name": name(str(model.get("model_id")))},
            },
        }
    return found


def _recorded_at(
    connection: Any, workspace_id: uuid.UUID, society_id: uuid.UUID, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """When each event's minute was recorded, in a person's time; a back-fill keeps it."""
    if not event_ids:
        return {}
    rows = connection.execute(
        "select event_id, recorded_at from world_society_event "
        "where workspace_id=%s and society_id=%s and event_id = any(%s)",
        (workspace_id, society_id, event_ids),
    ).fetchall()
    return {uuid.UUID(str(one["event_id"])): one["recorded_at"].isoformat() for one in rows}


def option_did(option: Mapping[str, Any], rules: MomentRules) -> dict[str, Any]:
    """What a decision's option does, in a branch's shape: its branch kind (a walk to a chosen
    spot :data:`WENT_TO_SPOT`, None for another kind the rules give none), the target it goes to or
    takes in hand, and who it is with or said to."""
    addressee = option.get("addressee_id") or option.get("partner_id")
    kind = str(option.get("kind"))
    return {
        "kind": rules.branch_kinds.get(kind) or (WENT_TO_SPOT if kind == POINT_KIND else None),
        "target": {"target_id": option.get("target_id"), "activity": option.get("activity")}
        if option.get("target_id") is not None
        else None,
        "with": None if addressee is None else str(addressee),
    }


def chosen_dids(
    connection: Any,
    workspace_id: uuid.UUID,
    society_id: uuid.UUID,
    requests: Iterable[uuid.UUID],
    rules: MomentRules | None = None,
) -> dict[uuid.UUID, dict[str, Any]]:
    """What each applied decision's chosen option did (:func:`option_did`), from its receipt, so a
    person's day says what was done rather than the choice as offered; a decision whose receipt
    holds no proposal is absent."""
    rules = load_rules() if rules is None else rules
    asked = sorted(set(requests), key=str)
    if not asked:
        return {}
    rows = connection.execute(
        "select request_id, document->'proposal'->'option' as option "
        "from world_society_decision where workspace_id=%s and society_id=%s "
        "and request_id = any(%s)",
        (workspace_id, society_id, asked),
    ).fetchall()
    return {
        uuid.UUID(str(row["request_id"])): option_did(row["option"], rules)
        for row in rows
        if isinstance(row["option"], Mapping)
    }


def _branches(
    connection: Any,
    workspace_id: uuid.UUID,
    society_id: uuid.UUID,
    requests: list[uuid.UUID],
    rules: MomentRules,
    name: Callable[[str], str | None],
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Every answered ask (0216) of each request, oldest first, as a branch."""
    if not requests:
        return {}
    originals = {
        uuid.UUID(str(one["request_id"])): one["label"]
        for one in connection.execute(
            "select request_id, document->'proposal'->'option'->>'label' as label "
            "from world_society_decision where workspace_id=%s and society_id=%s "
            "and request_id = any(%s)",
            (workspace_id, society_id, requests),
        ).fetchall()
    }
    rows = connection.execute(
        "select ask_id, request_id, provider, model_id, document, asked_at "
        "from world_society_decision_ask where workspace_id=%s and society_id=%s "
        "and request_id = any(%s) and status='accepted' order by asked_at, ask_id",
        (workspace_id, society_id, requests),
    ).fetchall()
    found: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for one in rows:
        proposal = one["document"].get("proposal") if isinstance(one["document"], Mapping) else None
        option = proposal.get("option") if isinstance(proposal, Mapping) else None
        if not isinstance(option, Mapping):
            continue
        request = uuid.UUID(str(one["request_id"]))
        did = option_did(option, rules)
        line = proposal.get("line") if isinstance(proposal, Mapping) else None
        found.setdefault(request, []).append(
            {
                "ask_id": str(one["ask_id"]),
                "asked_at": one["asked_at"].isoformat(),
                "model": {
                    "provider": one["provider"],
                    "model_id": one["model_id"],
                    "name": name(str(one["model_id"])),
                },
                "same_choice": option.get("label") == originals.get(request),
                # Another model's answer of a kind the rules give no branch kind carries on.
                **did,
                "kind": rules.branch_kinds.get(str(option.get("kind")), "carried_on"),
                "said": None if not line else {"line": str(line)},
                "scene": None,
                "picture": None,
            }
        )
    return found


def merge_moments(moments: list[dict[str, Any]], rules: MomentRules) -> list[dict[str, Any]]:
    """What a person reads as one moment, from moments oldest first: a reply within the exchange's
    minutes is a line of the moment it answers (up to the rule's lines); two characters going to the
    same place in the same minute, or one following the other there within the rule's minutes, are
    one going. A merged moment keeps the first one's time and who decided it, and every branch of
    the moments it was made from, each naming whose decision it answers."""
    merged: list[dict[str, Any]] = []
    for moment in moments:
        held = merged[-1] if merged else None
        last = (
            None if held is None else (held["said"][-1]["tick"] if held["said"] else held["tick"])
        )
        if (
            held is not None
            and last is not None
            and moment["kind"] == "spoke"
            and held["kind"] in _SPOKEN
            and set(held["subjects"]) == set(moment["subjects"])
            and moment["tick"] - last <= rules.exchange_minutes
            and len(held["said"]) + len(moment["said"]) <= rules.lines_most
        ):
            held["said"].extend(moment["said"])
            continue
        partner = _going_with(merged, moment, rules)
        if partner is not None:
            joining = moment["subjects"][0] if moment["kind"] == "followed" else None
            for subject in (joining,) if joining else moment["subjects"]:
                if subject not in partner["subjects"]:
                    partner["subjects"].append(subject)
            branches = [*partner["branches"], *moment["branches"]]
            if moment["kind"] == "went" and partner["kind"] == "followed":
                # The going a follower joined: the went's place and target, the first's time.
                follower = partner["subjects"][0]
                partner.update({key: moment[key] for key in ("kind", "place", "target", "scene")})
                partner["subjects"] = [moment["subjects"][0], follower]
            partner["branches"] = sorted(branches, key=lambda one: (one["asked_at"], one["ask_id"]))
            continue
        merged.append(moment)
    return merged


def _going_with(
    merged: list[dict[str, Any]], moment: dict[str, Any], rules: MomentRules
) -> dict[str, Any] | None:
    """The moment an earlier going this one is part of, or None."""
    for held in reversed(merged):
        if moment["tick"] - held["tick"] > rules.merge_minutes:
            return None
        kinds = (held["kind"], moment["kind"])
        same_place = bool(held.get("target")) and held.get("target") == moment.get("target")
        if (
            (kinds == ("went", "went") and same_place)
            or (kinds == ("followed", "went") and held["subjects"][1:2] == moment["subjects"][:1])
            or (kinds == ("went", "followed") and moment["subjects"][1:2] == held["subjects"][:1])
        ):
            return held
    return None


def _session_of(tick: int, sessions: Sequence[Mapping[str, Any]]) -> str | None:
    """The run a minute was played in, by the runs' minute windows."""
    for one in sessions:
        opened = one.get("opened") or {}
        closed = one.get("closed") or {}
        start = opened.get("start_tick")
        end = closed.get("end_tick")
        if start is not None and tick > int(start) and (end is None or tick <= int(end)):
            return str(one["session_id"])
    return None


def touched_spans(
    connection: Any, workspace_id: uuid.UUID, row: Mapping[str, Any]
) -> list[tuple[uuid.UUID, Any, Any]]:
    """When the person's hand was on each being of a society (H18 as amended: a resident is in the
    person's story while they touch it), as ``(being, from, until)`` in recorded time, ``None``
    for an open end, read from what it stores: from the choice that gives a being a model, a
    person playing or an outside program until the choice that sets it back to its routine, each
    choice read as every reader reads it (a play's end restores what it had before); from a run's
    request for a being recorded while no such span is open (one asked before choices were kept)
    until the next choice that sets it back; and always for a being placed in it (a personality
    is written on a placed being)."""
    from exulanica.world.decision_roles import decision_roles
    from exulanica.world.society_model_choice_repository import choice_steps, decider_of

    stored = connection.execute(
        "select document, recorded_at from world_society_model_choice "
        "where workspace_id=%s and world_id=%s and society_id=%s order by choice_seq",
        (workspace_id, row["world_id"], row["society_id"]),
    ).fetchall()
    # Each being's hand on (True) or off (False) as each record left it: a choice, then a request.
    marks: list[tuple[Any, int, str, bool]] = []
    for role in decision_roles():
        choices = [
            {
                **one["document"],
                "decider": decider_of(one["document"]),
                "recorded_at": one["recorded_at"],
            }
            for one in stored
            if role.reads_choice(str(one["document"].get("profile", "")))
        ]
        # One pass over the role's choices: each step as the one fold every reader reads leaves it.
        for choice, after, _since in choice_steps(role, choices):
            for subject in choice.get(role.choice_subjects, ()):
                held = after.get(subject)
                on = held is not None and held["decider"].get("kind") != "routine"
                marks.append((choice["recorded_at"], 0, str(subject), on))
    requests = connection.execute(
        "select subject_id, recorded_at from world_society_decision_request "
        "where workspace_id=%s and society_id=%s",
        (workspace_id, row["society_id"]),
    ).fetchall()
    marks += [(one["recorded_at"], 1, str(one["subject_id"]), True) for one in requests]
    spans: list[tuple[str, Any, Any]] = []
    opened: dict[str, Any] = {}
    for at, _order, subject, on in sorted(marks, key=lambda mark: (mark[0], mark[1])):
        if on and subject not in opened:
            opened[subject] = at
        elif not on and subject in opened:
            spans.append((subject, opened.pop(subject), at))
    spans += [(subject, at, None) for subject, at in opened.items()]
    state = row.get("state") or {}
    spans += [
        (str(person.get("id")), None, None)
        for person in state.get("inhabitants", ())
        if person.get("came_by") == "placed"
    ]
    found = [(being, start, until) for subject, start, until in spans if (being := _uuid(subject))]
    return sorted(found, key=lambda span: (str(span[0]), str(span[1]), str(span[2])))


def read_moments(
    connection: Any,
    workspace_id: uuid.UUID,
    row: Mapping[str, Any],
    *,
    before: int | None,
    limit: int,
    sessions: Sequence[Mapping[str, Any]],
    model_name: Callable[[str], str | None],
    rules: MomentRules | None = None,
    story: bool = False,
) -> dict[str, Any]:
    """A version's moments, newest last, at most ``limit`` before minute ``before``: each with its
    lines (an exchange joins the moment it answers), who decided, where, its run, its scene and the
    other models' answers to its decision as branches. ``more`` says whether earlier ones exist.
    With ``story``, only the moments a person's History draws (H18): each one a model, a person
    playing or an outside program decided, and each one with a being recorded while the person's
    hand was on it (:func:`touched_spans`, by the time its anchor event was recorded); ``before``,
    ``limit`` and ``more`` count within them."""
    rules = load_rules() if rules is None else rules
    society_id = row["society_id"]
    spans = touched_spans(connection, workspace_id, row) if story else []
    rows = connection.execute(
        "select moment_id, tick, kind, anchor_event_id, event_ids, request_id, subjects, document "
        "from world_society_moment m where workspace_id=%s and society_id=%s "
        "and (%s::int is null or tick < %s::int) "
        "and (not %s or document->'decider'->>'kind' = any(%s) or exists ("
        # A being of the moment whose span holds the time its anchor event was recorded.
        "select 1 from unnest(%s::uuid[], %s::timestamptz[], %s::timestamptz[]) "
        "as span(being, opened, closed) where span.being = any(m.subjects) and "
        "(span.opened is null and span.closed is null or exists ("
        "select 1 from world_society_event e where e.workspace_id=m.workspace_id "
        "and e.society_id=m.society_id and e.event_id=m.anchor_event_id "
        "and (span.opened is null or e.recorded_at >= span.opened) "
        "and (span.closed is null or e.recorded_at < span.closed))))) "
        "order by tick desc, moment_id desc limit %s",
        (
            workspace_id,
            society_id,
            before,
            before,
            story,
            list(_STORY_DECIDERS),
            [span[0] for span in spans],
            [span[1] for span in spans],
            [span[2] for span in spans],
            limit + 1,
        ),
    ).fetchall()
    more = len(rows) > limit
    rows = list(reversed(rows[:limit]))
    lines = _lines(
        connection,
        workspace_id,
        society_id,
        [uuid.UUID(str(event)) for one in rows for event in one["event_ids"]],
        model_name,
    )
    recorded = _recorded_at(
        connection,
        workspace_id,
        society_id,
        [uuid.UUID(str(one["anchor_event_id"])) for one in rows],
    )
    branches = _branches(
        connection,
        workspace_id,
        society_id,
        sorted({uuid.UUID(str(one["request_id"])) for one in rows if one["request_id"]}, key=str),
        rules,
        model_name,
    )
    moments: list[dict[str, Any]] = []
    for one in rows:
        document = one["document"]
        events = [uuid.UUID(str(event)) for event in one["event_ids"]]
        decider = dict(document.get("decider") or {})
        model = decider.get("model")
        moments.append(
            {
                "moment_id": str(one["moment_id"]),
                "tick": int(one["tick"]),
                "at": recorded.get(uuid.UUID(str(one["anchor_event_id"]))),
                "session_id": _session_of(int(one["tick"]), sessions),
                "kind": one["kind"],
                "subjects": [str(subject) for subject in one["subjects"]],
                # The decision that made it, so a page can open it; none for a routine's moment.
                "request_id": None if one["request_id"] is None else str(one["request_id"]),
                "place": document.get("place"),
                "target": document.get("target"),
                "with": None if document.get("thing") is None else {"thing": document["thing"]},
                "said": [lines[event] for event in events if event in lines],
                "decider": {
                    "kind": decider.get("kind", "routine"),
                    "model": None
                    if not isinstance(model, Mapping)
                    else {**model, "name": model_name(str(model.get("model_id")))},
                },
                "scene": document.get("scene"),
                "picture": None,
                # Each answer names whose decision it answers, so a going two made together keeps
                # both people's (merge_moments).
                "branches": []
                if one["request_id"] is None
                else [
                    {**branch, "by": str(one["subjects"][0])}
                    for branch in branches.get(uuid.UUID(str(one["request_id"])), [])
                ],
            }
        )
    moments = merge_moments(moments, rules)
    return {
        "profile": MOMENTS_PROFILE,
        "version_id": str(row["version_id"]),
        "rule_version": rules.profile,
        "now": {"tick": int(row["current_tick"])},
        "moments": moments,
        "more": more,
    }
