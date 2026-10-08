"""What a being of a society of things notices around it this minute, built by rule.

A decider (a model, a visitor's own program, an outside agent) is shown a being's options and the
lines it heard; :func:`surroundings` adds what the being would see where it stands: the place it
stands at, the other beings near it (who, how far, what each is doing and holding, whether it came
from elsewhere and whether it hears this being), and the loose things near it and what each is good
for. Everything in it is read from the society's stored state and the input its minute consumed,
so a replay that rebuilds a request rebuilds this block to the byte, and nothing in it is written
by a model.

**Words come from data.** A being is named as the page names it, in the form the say and give
options use, so a decider can match the two; its kind and what it holds are their kinds' labels;
what it is doing is its routine's activity words; what a thing is good for is the words the
offers catalog states for each offer its kind makes, read from the version :class:`NoticeTerms`
names, so a later catalog never changes what a stored request showed.

**Withheld by construction.** No look (no look reference enters a society's state or input), no
decider or model of another being, no identifier, position or heading, and no free text: every
string is a kind label, a page name, or activity and offer words. A saved name a page name might
carry is the boundary's to withhold (:func:`withhold`).

**Bounded.** At most :attr:`NoticeTerms.beings_maximum` beings and
:attr:`NoticeTerms.things_maximum` things within :attr:`NoticeTerms.reach_mm`, nearest first by
the straight line, ties by identifier, the rest counted; and the whole block within
:attr:`NoticeTerms.bytes_maximum` bytes of canonical JSON, the farthest entry dropped first (and
counted) until it fits.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.things.catalogs import offers_of_version
from exulanica.world.placed_things import ThingKindReference, shipped_kind

__all__ = [
    "MORE_MAXIMUM",
    "SURROUNDINGS_VERSION",
    "NoticeTerms",
    "surroundings",
    "surroundings_lines",
    "withhold",
]

#: The shape this module builds and the words it uses for what a being is doing.
SURROUNDINGS_VERSION: Final = 1
#: The most beings or things a block counts beyond those it lists.
MORE_MAXIMUM: Final = 99
#: How near the access point of a place a being stands for the place to be where it stands.
_AT_PLACE_MM: Final = 2_000
#: The offer a place's affordance is read as, for the words of what the place is good for.
_AFFORDANCE_OFFERS: Final = {"rest": "rest_at", "visit": "visit"}


@dataclass(frozen=True, slots=True)
class NoticeTerms:
    """How far a being notices, how many beings and things it is shown, how many bytes the block
    may take, how far its own line carries (whether another hears it) and which version of the
    offers catalog its words are read from."""

    reach_mm: int
    beings_maximum: int
    things_maximum: int
    bytes_maximum: int
    hearing_reach_mm: int
    offers_version: int

    def __post_init__(self) -> None:
        for name in ("reach_mm", "beings_maximum", "things_maximum", "bytes_maximum"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} is a whole number of at least 1")
        if self.hearing_reach_mm < 0 or self.offers_version < 1:
            raise ValueError("the hearing reach and the offers version are whole numbers")


def _distance(a: Sequence[int], b: Sequence[int]) -> int:
    return math.isqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _kind(reference: Mapping[str, Any]) -> Any:
    return shipped_kind(ThingKindReference(**reference))


def _label(reference: Mapping[str, Any]) -> str:
    return str(_kind(reference).document["label"])


def _offers(kind: Any) -> list[str]:
    return [str(offer["key"]) for offer in kind.document["offers"]]


def _metres(distance_mm: int) -> int:
    """Whole metres, rounded as the say and hands options round their distances."""
    return round(distance_mm / 1000)


def _who(person: Mapping[str, Any]) -> str:
    """A being as the say and give options name it."""
    from exulanica.world.society_decision_contract import page_name

    return page_name(person).lower()


def _doing(
    person: Mapping[str, Any],
    people: Mapping[str, Mapping[str, Any]],
    targets: Mapping[str, Mapping[str, Any]],
    routine: Any,
) -> str:
    """What a being is doing, in its routine's words: the activity at a place it is using, the
    routine's words for standing a while or talking (with whom), walking, or waiting."""
    from exulanica.world.society_decision_contract import _activity_label

    action = person["action"]
    if action["status"] == "active":
        if action["kind"] == "move":
            return "walking"
        target = targets.get(action.get("target_id") or "")
        if target is not None:
            return _activity_label(routine, target)[1]
        activity = routine.activities.get(action["kind"])
        if activity is not None and activity.setting == "pair":
            partner = people.get((person.get("goal") or {}).get("partner_id") or "")
            return activity.label if partner is None else f"{activity.label} with {_who(partner)}"
        if activity is not None:
            return str(activity.label)
    return "waiting"


def _at(
    person: Mapping[str, Any],
    document: Mapping[str, Any],
    routine: Any,
    words: Mapping[str, Any],
) -> dict[str, str] | None:
    """The place a being stands at: the enabled place whose access point is nearest it within
    :data:`_AT_PLACE_MM`, ties by its identifier, as its routine's activity words and the words of
    what it is good for; None where it stands at none."""
    from exulanica.world.society_decision_contract import _activity_label

    nodes = {node["node_id"]: node["position_mm"] for node in document["navigation"]["nodes"]}
    near = sorted(
        (_distance(person["position_mm"], nodes[target["node_id"]]), target["target_id"], target)
        for target in document["targets"]
        if target["enabled"] and target["node_id"] in nodes
    )
    if not near or near[0][0] > _AT_PLACE_MM:
        return None
    target = near[0][2]
    found = {"words": _activity_label(routine, target)[1]}
    offer = _AFFORDANCE_OFFERS.get(str(target["affordance"]))
    if offer is not None and offer in words:
        found["good_for"] = words[offer].words
    return found


def surroundings(
    state: Mapping[str, Any],
    document: Mapping[str, Any],
    subject_id: str,
    terms: NoticeTerms,
) -> dict[str, Any]:
    """What the being ``subject_id`` of the society of things ``state`` notices as its coming
    minute begins, over the input ``document`` its society consumed last, bounded by ``terms``."""
    from exulanica.world.society_decision_contract import _hears, kind_of
    from exulanica.world.society_planner import routine_of

    people = {person["id"]: person for person in state["inhabitants"]}
    me = people.get(subject_id)
    if me is None:
        raise ValueError("the subject is not one of this society's beings")
    words = offers_of_version(terms.offers_version)
    routine = routine_of(dict(document))
    targets = {target["target_id"]: target for target in document["targets"]}
    held: dict[str, list[str]] = {}
    for thing in state["things"]:
        if thing["held_by"] is not None:
            held.setdefault(thing["held_by"], []).append(_label(thing["kind"]))

    beings = sorted(
        (_distance(me["position_mm"], other["position_mm"]), other["id"], other)
        for other in state["inhabitants"]
        if other["id"] != subject_id
    )
    beings = [row for row in beings if row[0] <= terms.reach_mm]
    listed_beings = [
        {
            "who": _who(other),
            "kind": str(kind_of(other).document["label"]),
            "metres": _metres(distance),
            "doing": _doing(other, people, targets, routine),
            "holding": held.get(other["id"], []),
            "from_elsewhere": other.get("came_by") == "crossed",
            "hears_you": distance <= terms.hearing_reach_mm and _hears(kind_of(other)),
        }
        for distance, _, other in beings[: terms.beings_maximum]
    ]
    things = sorted(
        (_distance(me["position_mm"], thing["position_mm"]), thing["id"], thing)
        for thing in state["things"]
        if thing["held_by"] is None and thing.get("position_mm") is not None
    )
    things = [row for row in things if row[0] <= terms.reach_mm]
    listed_things = []
    for distance, _, thing in things[: terms.things_maximum]:
        kind = _kind(thing["kind"])
        listed_things.append(
            {
                "what": str(kind.document["label"]),
                "metres": _metres(distance),
                "good_for": [words[key].words for key in _offers(kind) if key in words],
            }
        )
    block = {
        "at": _at(me, document, routine, words),
        "beings": listed_beings,
        "more_beings": min(MORE_MAXIMUM, len(beings) - len(listed_beings)),
        "things": listed_things,
        "more_things": min(MORE_MAXIMUM, len(things) - len(listed_things)),
    }
    return _within(block, [row[0] for row in beings], [row[0] for row in things], terms)


def _within(
    block: dict[str, Any],
    beings_mm: Sequence[int],
    things_mm: Sequence[int],
    terms: NoticeTerms,
) -> dict[str, Any]:
    """``block`` within its byte bound: while it is over, the farther of its last listed being and
    last listed thing is dropped and counted, a thing first at an equal distance."""
    while len(canonical_json(block)) > terms.bytes_maximum:
        beings, things = block["beings"], block["things"]
        if not beings and not things:
            raise ValueError("the surroundings bound holds no block, not even an empty one")
        being_mm = beings_mm[len(beings) - 1] if beings else -1
        thing_mm = things_mm[len(things) - 1] if things else -1
        if thing_mm >= being_mm:
            block["things"] = things[:-1]
            block["more_things"] = min(MORE_MAXIMUM, block["more_things"] + 1)
        else:
            block["beings"] = beings[:-1]
            block["more_beings"] = min(MORE_MAXIMUM, block["more_beings"] + 1)
    return block


def withhold(block: Mapping[str, Any], carries: Callable[[str], bool]) -> dict[str, Any]:
    """``block`` without any being or thing one of whose words ``carries`` says holds what may not
    be shown (a saved name, for an outside program), each left out counted with the rest, and
    with no place it stands at whose words do; the block's other entries as they were."""
    beings = [entry for entry in block["beings"] if not any(carries(t) for t in _texts(entry))]
    things = [entry for entry in block["things"] if not any(carries(t) for t in _texts(entry))]
    at = block["at"]
    return {
        "at": None if at is not None and any(carries(t) for t in _texts(at)) else at,
        "beings": beings,
        "more_beings": min(MORE_MAXIMUM, block["more_beings"] + len(block["beings"]) - len(beings)),
        "things": things,
        "more_things": min(MORE_MAXIMUM, block["more_things"] + len(block["things"]) - len(things)),
    }


def _texts(entry: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    for value in entry.values():
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, list):
            found.extend(item for item in value if isinstance(item, str))
    return found


def surroundings_lines(block: Mapping[str, Any]) -> list[str]:
    """The block as a model reads it, after what the being holds: where it stands, the beings
    near it nearest first, then the things near it. Nothing where it notices nothing."""
    lines: list[str] = []
    at = block["at"]
    if at is not None:
        good = f" ({at['good_for']})" if "good_for" in at else ""
        lines.append(f"Where you stand: {at['words']}{good}.")
    if block["beings"] or block["more_beings"]:
        lines.append("Around you now:")
        for being in block["beings"]:
            parts = [f"{being['who']}, {_away(being['metres'])}", being["doing"]]
            if being["holding"]:
                parts.append("holding " + ", ".join(f"the {label}" for label in being["holding"]))
            if being["from_elsewhere"]:
                parts.append("from another world")
            if being["hears_you"]:
                parts.append("hears you")
            lines.append("- " + "; ".join(parts))
        if block["more_beings"]:
            lines.append(f"- and {block['more_beings']} more farther away")
    if block["things"] or block["more_things"]:
        lines.append("Things near you:")
        for thing in block["things"]:
            good = f" ({'; '.join(thing['good_for'])})" if thing["good_for"] else ""
            lines.append(f"- the {thing['what']}, {_away(thing['metres'])}{good}")
        if block["more_things"]:
            lines.append(f"- and {block['more_things']} more farther away")
    return lines


def _away(metres: int) -> str:
    return "beside you" if metres == 0 else f"{metres} m away"
