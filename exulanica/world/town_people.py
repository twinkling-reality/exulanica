"""A town's people as one document, ``exulanica.town-people/v1``: who lives and works where.

Who a town's residents are is data of the town, whichever engine its society runs: each resident's
home and household and, where the town gives one, their job: the premises, the position, the role
its use class names and the shift that position works. The document states exactly that and
nothing an engine keeps for itself (where anybody stands, what they need, what they are doing).

**Premises are named by the town's own records.** A home or a workplace is the subject its place
states for it (``city.premises:<identity>`` for a city's premises, ``site.structure:<identity>``
for a site's structure), never an engine's destination or target id, so a reader of any engine
finds it. Each premises a person may live or work at is described once, with what a card or a
prompt says of it (its use class, label and address number), the node its door stands at, the
places in a home it offers and its positions with the shift each works.

**A rule makes it, and the document names the rule.** :data:`RULE_V1` is the living town's own
assignment (:func:`~exulanica.world.society_living.initial_living_society`), draw for draw: one
resident in each place in a home in premises order; a seeded order of the residents, cut to the
routine's employment share where its policy states one, takes the positions workplace-first, one
at every workplace in a seeded order before a second at any; each position works the shift its use
class names for it in turn, started within the policy's jitter of the shift's own start. Two
residents share a household where they share a home. ``tests/test_town_people.py`` holds every
person of the document to the person that engine makes over the shipped towns.

The document holds the outcomes of the seed's draws and never the seed. It is canonical JSON named
by ``document_sha256``, the SHA-256 of every other key, and records the routine it was made under
(its binding: catalog versions, digest and any overlay) and the place it was made over (its id and
digest). Whether a person can walk from home to work is the engine's to check over its own graph,
as the living town does at genesis; a document states who the people are, not that a society over
its place starts.

Its profile grows only by optional fields. Its origin is ``derived``: made by a rule from the
town's records and a seed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.world.society import _number
from exulanica.world.society_catalogs import MINUTES_PER_DAY, RoutineModel

__all__ = [
    "FRAME_PROFILE",
    "ORIGIN_DERIVED",
    "PROFILE",
    "REASONS",
    "RULE_V1",
    "TownPeopleRefused",
    "people_frame",
    "people_from_frame",
    "resident_entry",
    "resident_of",
    "resident_premises",
    "town_people",
    "town_people_sha256",
    "validate_people_frame",
    "validate_town_people",
]

PROFILE: Final = "exulanica.town-people/v1"
#: What a town's people are made from before any draw: what a society input carries.
FRAME_PROFILE: Final = "exulanica.town-people-frame/v1"
#: The living town's own assignment, draw for draw (the module docstring states it).
RULE_V1: Final = "exulanica.town-people-rule/v1"
#: Made by a rule from the town's records and a seed.
ORIGIN_DERIVED: Final = "derived"

#: Why a person holds the job they hold, or none, in the living town's own words.
REASONS: Final = frozenset(
    {"works_at_premises", "keeps_no_job", "no_open_position", "lives_at_premises"}
)

_RESIDENT: Final = {"key": "resident", "label": "resident"}
_DOCUMENT_FIELDS: Final = frozenset(
    {
        "profile",
        "rule",
        "origin",
        "routine",
        "place",
        "day",
        "premises",
        "people",
        "document_sha256",
    }
)
_PREMISES_FIELDS: Final = frozenset(
    {"subject_id", "use_class", "label", "address_number", "node_id", "homes", "positions"}
)
_PERSON_FIELDS: Final = frozenset({"ordinal", "home", "job", "role", "reason"})
_FRAME_FIELDS: Final = frozenset(
    {
        "profile",
        "rule",
        "routine",
        "place",
        "day",
        "employment_share_milli",
        "shift_jitter_minutes",
        "population",
        "premises",
    }
)
_FRAME_PREMISES_FIELDS: Final = _PREMISES_FIELDS | {"destination_id", "role"}
_SHIFT_FIELDS: Final = frozenset({"key", "start_minute", "minutes"})


class TownPeopleRefused(ValueError):
    """A place no people document is made over, or a document that is not one, by name."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _refuse(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise TownPeopleRefused(code, message)


def town_people_sha256(document: Mapping[str, Any]) -> str:
    """The digest a people document is named by: SHA-256 over every key but the digest's own."""
    return sha256_of_canonical({k: v for k, v in document.items() if k != "document_sha256"}).hex()


def _span(seed: str, domain: str, ordinal: int, low: int, high: int) -> int:
    return low + _number(seed, domain, ordinal) % (high - low + 1)


def _shift(dest: Mapping[str, Any], index: int, routine: RoutineModel) -> dict[str, Any]:
    """The shift a workplace's position ``index`` works: the one its use class names for that
    position in turn, or the premises' one shift, under no key, where it names none."""
    use = routine.use_classes.get(dest["use_class"]) if dest["use_class"] else None
    if use is None or not use.shifts:
        stated = dest["shift"]
        _refuse(
            stated is not None,
            "position_states_no_shift",
            f"{dest['subject_id']} offers a position and states no shift for it",
        )
        return {"key": None, "start_minute": stated["start_minute"], "minutes": stated["minutes"]}
    shift = routine.shifts[use.shifts[index % len(use.shifts)]]
    return {"key": shift.key, "start_minute": shift.start_minute, "minutes": shift.minutes}


def people_frame(
    place: Mapping[str, Any],
    routine: RoutineModel,
    *,
    population: int | None = None,
) -> dict[str, Any]:
    """What the people of the town whose place document is ``place`` are made from, before any
    draw: :data:`FRAME_PROFILE`, a document a society input may carry.

    ``place`` is a validated living place (a town's city place or a site's, in any frame: only its
    id, its digest and its enabled destinations are read) and ``routine`` the routine it was made
    under. ``population`` is how many of the place's homes' places are lived in, every one where it
    is None. The frame states the rule that completes it, the routine by its binding, the place by
    id and digest, the minute the day starts at, the two policy figures the rule reads (the share
    who work, or none where the policy states none, and the shift jitter) and every premises that
    offers a place in a home or a position, in the place's destination order, which is the order
    the rule houses people in. It holds no seed and nothing drawn from one. A place that offers no
    place in a home is refused ``place_offers_no_homes``, and a population outside one to its
    places ``population_outside_homes``.
    """
    destinations = sorted(
        (d for d in place["destinations"] if d["enabled"]), key=lambda d: d["destination_id"]
    )
    premises = [
        {
            "destination_id": dest["destination_id"],
            "subject_id": dest["subject_id"],
            "use_class": dest["use_class"],
            "label": dest["label"],
            "address_number": dest["address_number"],
            "node_id": dest["node_id"],
            "role": None if dest["role"] is None else dict(dest["role"]),
            "homes": dest["resident_capacity"],
            "positions": [_shift(dest, i, routine) for i in range(dest["staff_capacity"])],
        }
        for dest in destinations
        if dest["resident_capacity"] or dest["staff_capacity"]
    ]
    places = sum(row["homes"] for row in premises)
    _refuse(bool(places), "place_offers_no_homes", "this place's premises offer no place in a home")
    size = places if population is None else population
    _refuse(
        type(size) is int and 1 <= size <= places,
        "population_outside_homes",
        f"this place's homes hold between 1 and {places} people",
    )
    policy = routine.policy
    frame = {
        "profile": FRAME_PROFILE,
        "rule": RULE_V1,
        "routine": routine.binding(),
        "place": {"place_id": place["place_id"], "document_sha256": place["document_sha256"]},
        "day": {"start_minute_of_day": policy["start_minute_of_day"]},
        "employment_share_milli": policy.get("employment_share_milli"),
        "shift_jitter_minutes": policy["shift_jitter_minutes"],
        "population": size,
        "premises": premises,
    }
    validate_people_frame(frame)
    return frame


def people_from_frame(seed: str, frame: Mapping[str, Any]) -> dict[str, Any]:
    """The people document a frame and a society seed make, by the rule the frame names.

    Pure of every catalog and of the place: the frame states all the rule reads, so a society
    whose first input carries one makes, and replays, the same people from that input and its own
    seed whatever is published later."""
    _refuse(
        isinstance(seed, str) and len(seed) == 64 and all(c in "0123456789abcdef" for c in seed),
        "seed_not_a_digest",
        "society seed must be a lowercase SHA-256",
    )
    validate_people_frame(frame)
    by_destination = {row["destination_id"]: row for row in frame["premises"]}
    homes = [row["destination_id"] for row in frame["premises"] for _ in range(row["homes"])]
    size = frame["population"]
    staff = [
        (row["destination_id"], index)
        for row in frame["premises"]
        for index in range(len(row["positions"]))
    ]
    order = sorted(range(size), key=lambda i: (_number(seed, "work", i), i))
    share = frame["employment_share_milli"]
    if share is not None:
        order = order[: size * share // 1000]
        staff = sorted(
            staff, key=lambda row: (row[1], _number(seed, f"workplace:{row[0]}", 0), row)
        )
    jobs = dict(zip(order, staff, strict=False))
    employed = set(order)
    jitter = frame["shift_jitter_minutes"]
    people = []
    for ordinal in range(size):
        home = by_destination[homes[ordinal]]
        person: dict[str, Any] = {
            "ordinal": ordinal,
            # One household a home under this rule: everybody in a home lives together.
            "home": {"subject_id": home["subject_id"], "household": 0},
            "job": None,
            "role": dict(home["role"]) if home["role"] is not None else dict(_RESIDENT),
            "reason": "lives_at_premises",
        }
        job = jobs.get(ordinal)
        if job is not None:
            workplace = by_destination[job[0]]
            shift = workplace["positions"][job[1]]
            start = shift["start_minute"] + _span(seed, "shift", ordinal, -jitter, jitter)
            person["job"] = {
                "subject_id": workplace["subject_id"],
                "position": job[1],
                "shift": {**shift, "start_minute": start % MINUTES_PER_DAY},
            }
            person["role"] = dict(workplace["role"])
            person["reason"] = "works_at_premises"
        elif staff and ordinal not in employed:
            person["reason"] = "keeps_no_job"
        elif staff:
            person["reason"] = "no_open_position"
        people.append(person)
    premises = [
        {key: row[key] for key in sorted(_PREMISES_FIELDS)}
        for row in sorted(frame["premises"], key=lambda row: row["subject_id"])
    ]
    document: dict[str, Any] = {
        "profile": PROFILE,
        "rule": frame["rule"],
        "origin": {"kind": ORIGIN_DERIVED},
        "routine": dict(frame["routine"]),
        "place": dict(frame["place"]),
        "day": dict(frame["day"]),
        "premises": premises,
        "people": people,
    }
    document["document_sha256"] = town_people_sha256(document)
    validate_town_people(document)
    return document


def town_people(
    seed: str,
    place: Mapping[str, Any],
    routine: RoutineModel,
    *,
    population: int | None = None,
) -> dict[str, Any]:
    """The people of the town whose place document is ``place``, by :data:`RULE_V1`: its frame
    (:func:`people_frame`) completed with ``seed``, the society seed of the town's world
    (:func:`people_from_frame`)."""
    _refuse(
        isinstance(seed, str) and len(seed) == 64 and all(c in "0123456789abcdef" for c in seed),
        "seed_not_a_digest",
        "society seed must be a lowercase SHA-256",
    )
    return people_from_frame(seed, people_frame(place, routine, population=population))


def resident_premises(people: Mapping[str, Any]) -> list[dict[str, Any]]:
    """What a society keeps, once, of the premises its town's people live and work at: each of
    ``people``'s premises in the document's order by subject, use class, label and address
    number, which a resident names by its place in this list."""
    return [
        {
            "subject_id": row["subject_id"],
            "use_class": row["use_class"],
            "label": row["label"],
            "address_number": row["address_number"],
        }
        for row in people["premises"]
    ]


def resident_entry(people: Mapping[str, Any], person: Mapping[str, Any]) -> dict[str, Any]:
    """What a society keeps on one of its people of who they are in the town: ``person``'s entry
    of ``people`` without its ordinal, its home and its workplace each named by the premises'
    place in :func:`resident_premises`, so a society states what a premises is called once
    however many live or work there."""
    index = {row["subject_id"]: number for number, row in enumerate(people["premises"])}
    home, job = person["home"], person["job"]
    return {
        "home": {"premises": index[home["subject_id"]], "household": home["household"]},
        "job": None
        if job is None
        else {
            "premises": index[job["subject_id"]],
            "position": job["position"],
            "shift": dict(job["shift"]),
        },
        "role": dict(person["role"]),
        "reason": person["reason"],
    }


def resident_of(state: Mapping[str, Any], person: Mapping[str, Any]) -> dict[str, Any] | None:
    """Who ``person`` of a society's ``state`` is in their town, read the same way from either
    engine that keeps one, or None for anybody who is no resident (a being its author placed, a
    visitor, a person of a society with no homes).

    Answers ``role`` (key and label), ``works`` (whether they hold a job), ``shift`` (the start
    minute of the day and the minutes of their shift, or None) and ``home`` and ``job`` as the
    engine names a premises: a society of things by the town's record subject, with what the
    premises is called (use class, label, address number); a living town by its place's
    destination id."""
    resident = person.get("resident")
    if isinstance(resident, Mapping):
        premises = state["people"]["premises"]
        job = resident["job"]
        return {
            "role": dict(resident["role"]),
            "works": job is not None,
            "shift": None
            if job is None
            else {
                "start_minute": job["shift"]["start_minute"],
                "minutes": job["shift"]["minutes"],
            },
            "home": dict(premises[resident["home"]["premises"]]),
            "job": None if job is None else dict(premises[job["premises"]]),
        }
    home, role = person.get("home"), person.get("role")
    if not isinstance(home, Mapping) or not isinstance(role, Mapping):
        return None
    work = person.get("work")
    return {
        "role": {"key": role["key"], "label": role["label"]},
        "works": work is not None,
        "shift": None
        if work is None
        else {"start_minute": work["shift_start_minute"], "minutes": work["shift_minutes"]},
        "home": {"destination_id": home["destination_id"]},
        "job": None if work is None else {"destination_id": work["destination_id"]},
    }


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _whole(value: Any, minimum: int, maximum: int | None = None) -> bool:
    return type(value) is int and value >= minimum and (maximum is None or value <= maximum)


def _digest(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _shift_shape(shift: Any, what: str) -> None:
    _refuse(
        isinstance(shift, Mapping)
        and set(shift) == _SHIFT_FIELDS
        and (shift["key"] is None or _text(shift["key"]))
        and _whole(shift["start_minute"], 0, MINUTES_PER_DAY - 1)
        and _whole(shift["minutes"], 1, MINUTES_PER_DAY),
        "malformed_people",
        f"{what} states a shift: a key or none, a start minute of the day and its minutes",
    )


def _premises_shape(row: Any, fields: frozenset[str]) -> None:
    _refuse(
        isinstance(row, Mapping)
        and set(row) == fields
        and _text(row["subject_id"])
        and (row["use_class"] is None or _text(row["use_class"]))
        and (row["label"] is None or _text(row["label"]))
        and (row["address_number"] is None or _whole(row["address_number"], 0))
        and _text(row["node_id"])
        and _whole(row["homes"], 0)
        and isinstance(row["positions"], list)
        and bool(row["homes"] or row["positions"]),
        "malformed_people",
        "a premises states its subject, what it is called, its door's node, its places in a "
        "home and its positions, and offers at least one of the two",
    )
    for index, shift in enumerate(row["positions"]):
        _shift_shape(shift, f"position {index} of {row['subject_id']}")


def _made_under(document: Mapping[str, Any]) -> None:
    """What a frame and a people document both state of where they came from."""
    _refuse(document["rule"] == RULE_V1, "malformed_people", "unknown people rule")
    routine = document["routine"]
    _refuse(
        isinstance(routine, Mapping)
        and {"catalog_versions", "sha256"}
        <= set(routine)
        <= {"catalog_versions", "sha256", "overlay"}
        and _digest(routine["sha256"])
        and isinstance(routine["catalog_versions"], Mapping),
        "malformed_people",
        "people are made under a routine named by its binding",
    )
    place = document["place"]
    _refuse(
        isinstance(place, Mapping)
        and set(place) == {"place_id", "document_sha256"}
        and _text(place["place_id"])
        and _digest(place["document_sha256"]),
        "malformed_people",
        "people are made over a place named by id and digest",
    )
    day = document["day"]
    _refuse(
        isinstance(day, Mapping)
        and set(day) == {"start_minute_of_day"}
        and _whole(day["start_minute_of_day"], 0, MINUTES_PER_DAY - 1),
        "malformed_people",
        "people's day states the minute it starts at",
    )


def validate_people_frame(frame: Any) -> None:
    """Hold ``frame`` to :data:`FRAME_PROFILE`, or refuse it ``malformed_people``: its exact keys,
    its premises once each in destination order with a subject of their own, a role wherever a
    premises offers a position, and a population its homes hold."""
    _refuse(
        isinstance(frame, Mapping) and set(frame) == _FRAME_FIELDS,
        "malformed_people",
        "a people frame states exactly its profile's keys",
    )
    _refuse(
        frame["profile"] == FRAME_PROFILE, "malformed_people", f"a people frame is {FRAME_PROFILE}"
    )
    _made_under(frame)
    share = frame["employment_share_milli"]
    _refuse(
        (share is None or _whole(share, 0, 1000))
        and _whole(frame["shift_jitter_minutes"], 0, MINUTES_PER_DAY - 1),
        "malformed_people",
        "a people frame states the share who work, or none, and the shift jitter",
    )
    premises = frame["premises"]
    _refuse(isinstance(premises, list), "malformed_people", "premises is a list")
    for row in premises:
        _refuse(
            isinstance(row, Mapping) and _text(row.get("destination_id")),
            "malformed_people",
            "a frame's premises states the place's destination it is",
        )
        _premises_shape(row, _FRAME_PREMISES_FIELDS)
        role = row["role"]
        _refuse(
            (role is None and not row["positions"])
            or (
                isinstance(role, Mapping)
                and set(role) == {"key", "label"}
                and _text(role["key"])
                and _text(role["label"])
            ),
            "malformed_people",
            f"{row['subject_id']} states the role its people take, by key and label",
        )
    order = [row["destination_id"] for row in premises]
    _refuse(
        order == sorted(set(order))
        and len({row["subject_id"] for row in premises}) == len(premises),
        "malformed_people",
        "a frame's premises are stated once each, in destination order",
    )
    _refuse(
        _whole(frame["population"], 1, sum(row["homes"] for row in premises)),
        "malformed_people",
        "a frame's population is between one and the places its homes offer",
    )


def validate_town_people(document: Any) -> None:
    """Hold ``document`` to the profile, or refuse it ``malformed_people``: its exact keys, its
    premises in subject order with each stated once, its people in ordinal order from 0, nobody
    in a home that has no place left or at a position that is not their workplace's or is somebody
    else's, each worker's shift their position's own (its start aside), and its digest."""
    _refuse(
        isinstance(document, Mapping) and set(document) == _DOCUMENT_FIELDS,
        "malformed_people",
        "a people document states exactly its profile's keys",
    )
    _refuse(document["profile"] == PROFILE, "malformed_people", f"a people document is {PROFILE}")
    _refuse(
        document["origin"] == {"kind": ORIGIN_DERIVED}, "malformed_people", "unknown people origin"
    )
    _made_under(document)
    premises = document["premises"]
    _refuse(isinstance(premises, list), "malformed_people", "premises is a list")
    by_subject: dict[str, Mapping[str, Any]] = {}
    for row in premises:
        _premises_shape(row, _PREMISES_FIELDS)
        by_subject[row["subject_id"]] = row
    _refuse(
        [row["subject_id"] for row in premises] == sorted(by_subject),
        "malformed_people",
        "premises are stated once each, in subject order",
    )
    people = document["people"]
    _refuse(
        isinstance(people, list) and bool(people), "malformed_people", "a town's people are a list"
    )
    housed: Counter[str] = Counter()
    taken: set[tuple[str, int]] = set()
    for ordinal, person in enumerate(people):
        _refuse(
            isinstance(person, Mapping)
            and set(person) == _PERSON_FIELDS
            and person["ordinal"] == ordinal
            and type(person["ordinal"]) is int,
            "malformed_people",
            "people are stated in ordinal order from 0, each with exactly a person's keys",
        )
        home, job, role = person["home"], person["job"], person["role"]
        _refuse(
            isinstance(home, Mapping)
            and set(home) == {"subject_id", "household"}
            and home["subject_id"] in by_subject
            and _whole(home["household"], 0),
            "malformed_people",
            f"person {ordinal} lives at a premises the document states, in a household of it",
        )
        housed[home["subject_id"]] += 1
        _refuse(
            housed[home["subject_id"]] <= by_subject[home["subject_id"]]["homes"],
            "malformed_people",
            f"{home['subject_id']} houses more people than it has places in a home",
        )
        _refuse(
            isinstance(role, Mapping)
            and set(role) == {"key", "label"}
            and _text(role["key"])
            and _text(role["label"]),
            "malformed_people",
            f"person {ordinal} states a role by key and label",
        )
        _refuse(
            person["reason"] in REASONS
            and (person["reason"] == "works_at_premises") == (job is not None),
            "malformed_people",
            f"person {ordinal}'s reason says whether they hold a job",
        )
        if job is None:
            continue
        _refuse(
            isinstance(job, Mapping)
            and set(job) == {"subject_id", "position", "shift"}
            and job["subject_id"] in by_subject
            and _whole(job["position"], 0)
            and job["position"] < len(by_subject[job["subject_id"]]["positions"]),
            "malformed_people",
            f"person {ordinal} works a position their workplace states",
        )
        _shift_shape(job["shift"], f"person {ordinal}'s job")
        position = by_subject[job["subject_id"]]["positions"][job["position"]]
        _refuse(
            job["shift"]["key"] == position["key"]
            and job["shift"]["minutes"] == position["minutes"],
            "malformed_people",
            f"person {ordinal} works their position's shift, started at their own minute",
        )
        seat = (job["subject_id"], job["position"])
        _refuse(seat not in taken, "malformed_people", f"two people hold {seat[0]}'s one position")
        taken.add(seat)
    _refuse(
        document["document_sha256"] == town_people_sha256(document),
        "malformed_people",
        "people digest mismatch",
    )
