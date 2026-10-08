"""Society-of-things terms for the sixth person score, with the third score's anchored math.

The sixth version of the score of the role "a person in your world",
``assets/catalogs/society/society-person-score.v6.json``, scores the group of a comparison of a
society of things (``exulanica-society/v7``) by the third score's two terms, weights and anchors:
half need relief, half variety, waiting scoring 0 and the routine 1 on the same seed, nothing
clipped, with its reliability classes and exclusions. Need relief is read exactly as the third
score reads it, from the purposeful need every being of a society of things carries.

Variety is extended. A kind counts once per person in the window, as before, and a person's kinds
are the routine activities the third score counts (what a minute's state names while the person is
doing something, never walking or waiting) and also the acts the society's modules record for that
person: a line said (``said``) and the hands acts (``picked_up``, ``put_down``, ``gave``,
``took``), each read from its event, whose subject is the being that did it. A line never changes
what its speaker is doing and a hands act is recorded only by its event, so no kind is counted
twice. The routine never speaks and never uses its hands, so a model that only chooses the
routine's activities scores near 1, one that also speaks and hands things over scores above it, and
one that idles scores toward 0; since each kind counts once, saying many lines raises nothing.

Reported beside the terms and never weighed: how many of each act the group did, how many lines it
said and how many of them nearly repeat an earlier line (the THINGS-LINE-VARIETY measurement's
metric: a line whose word set has a token-set Jaccard of at least a half with an earlier line its
speaker said in the run, or with the line it answers, the last said to it or to everyone near it
that it heard before it spoke), and the hands acts dropped, by reason. What each model answered is
the second version's reliability, as for every score. Line quality is not judged.

The import rules keep the model client, the asking path and the API out of this module's reach (the
"A person's score cannot read a model" contract in ``pyproject.toml``).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from exulanica.world import society_score_v2, society_score_v3
from exulanica.world.society_catalogs import STATES_AND_ACTS
from exulanica.world.society_score import ScoreRefused, _minute_class

__all__ = ["ACT_KINDS", "CATALOG_VERSION", "near_repeat", "run_terms", "score", "validate_terms"]

#: The version of the ``society-person-score`` catalog this module computes.
CATALOG_VERSION: Final = 6
#: The acts a society of things records by an event whose subject did them, each a kind of variety.
ACT_KINDS: Final = ("said", "picked_up", "put_down", "gave", "took")
#: A hands act dropped by name, reported by its reason.
HANDS_MISSED: Final = "hands_missed"
_WORD: Final = re.compile(r"[a-z0-9']+")


def _words(line: str) -> frozenset[str]:
    return frozenset(_WORD.findall(line.lower()))


def near_repeat(line: str, earlier: Iterable[str]) -> bool:
    """Whether ``line`` shares at least half of all its words with any of ``earlier`` (token-set
    Jaccard of a half or more); two lines with no words at all are alike."""
    left = _words(line)
    for other in earlier:
        right = _words(other)
        union = left | right
        if not union or 2 * len(left & right) >= len(union):
            return True
    return False


def _answered(person: Mapping[str, Any] | None, speaker: str, tick: int) -> str | None:
    """The last line said to ``speaker``, or to everyone near it, that it heard before ``tick``."""
    heard = [] if person is None else person.get("heard", [])
    before = [h for h in heard if h["to"] in (speaker, None) and int(h["tick"]) < tick]
    return str(before[-1]["line"]) if before else None


def run_terms(
    states: Sequence[Mapping[str, Any]],
    events: Iterable[Any],
    *,
    people: Iterable[str],
    threshold: int,
    choice_points: int,
    score: society_score_v2.PersonScore,
) -> dict[str, Any]:
    """The exact terms of one run of a society of things over ``people``: the second version's
    terms, each person's activity count extended by the acts it did, and the acts, lines and
    dropped hands acts reported. ``states`` are its minutes after genesis, in order."""
    events = list(events)
    members = tuple(sorted(people))
    terms = society_score_v2.run_terms(
        states,
        events,
        people=members,
        threshold=threshold,
        choice_points=choice_points,
        score=score,
    ).document()
    held = frozenset(members)
    seen: dict[str, set[str]] = {subject: set() for subject in members}
    for state in states:
        for person in state["inhabitants"]:
            if person["id"] in held and _minute_class(person) == "doing":
                seen[person["id"]].add(str(person["action"]["kind"]))
    began = {int(state["tick"]): state for state in states}
    acts: Counter[str] = Counter()
    missed: Counter[str] = Counter()
    lines: list[tuple[str, str, str | None]] = []
    for event in events:
        kind, subject, document = society_score_v2._event_parts(event)
        if subject not in held:
            continue
        if kind in ACT_KINDS:
            seen[subject].add(kind)
            acts[kind] += 1
        if kind == HANDS_MISSED:
            missed[str(document["reason"])] += 1
        if kind == "said":
            tick = int(document["tick"])
            # What the speaker had heard as the minute it spoke in began.
            before = began.get(tick - 1)
            speaker = None
            if before is not None:
                speaker = next((p for p in before["inhabitants"] if p["id"] == subject), None)
            line = str(document["thing"]["line"])
            lines.append((subject, line, _answered(speaker, subject, tick)))
    repeats = 0
    for index, (speaker, line, answers) in enumerate(lines):
        earlier = [said for who, said, _ in lines[:index] if who == speaker]
        if answers is not None:
            earlier.append(answers)
        repeats += near_repeat(line, earlier)
    return {
        **terms,
        "activities": {subject: len(kinds) for subject, kinds in sorted(seen.items())},
        "acts": {kind: acts[kind] for kind in ACT_KINDS},
        "lines": {"said": len(lines), "near_repeats": repeats},
        HANDS_MISSED: dict(sorted(missed.items())),
    }


def validate_terms(document: Mapping[str, Any]) -> society_score_v2.RunTerms:
    """A stored sixth-score term document with what it reports of acts, lines and dropped hands
    acts, or a refusal."""
    acts = document.get("acts")
    lines = document.get("lines")
    missed = document.get(HANDS_MISSED)
    counts = [
        *(acts.values() if isinstance(acts, dict) else ()),
        *(lines.values() if isinstance(lines, dict) else ()),
        *(missed.values() if isinstance(missed, dict) else ()),
    ]
    if (
        not isinstance(acts, dict)
        or set(acts) != set(ACT_KINDS)
        or not isinstance(lines, dict)
        or set(lines) != {"said", "near_repeats"}
        or not isinstance(missed, dict)
        or any(type(count) is not int or count < 0 for count in counts)
        or lines["near_repeats"] > lines["said"]
        or lines["said"] != acts["said"]
    ):
        raise ScoreRefused("things_terms_binding", "the stored terms report acts, lines and hands")
    return society_score_v2.RunTerms.from_document(document)


def score(catalog: Mapping[str, Mapping[str, Any]]) -> society_score_v3.PersonScore:
    """The sixth catalog has the third's weights and reliability mapping exactly; its variety, and
    nothing else, reads the acts beside the minutes (:data:`STATES_AND_ACTS`)."""
    variety = catalog.get(society_score_v3.VARIETY)
    if variety is None or variety["reads"] != STATES_AND_ACTS:
        raise ScoreRefused("score_terms_not_computed", "the sixth score's variety reads acts")
    if any(
        entry["reads"] == STATES_AND_ACTS
        for key, entry in catalog.items()
        if key != society_score_v3.VARIETY
    ):
        raise ScoreRefused("score_terms_not_computed", "only variety reads acts")
    return society_score_v3.person_score(
        {**catalog, society_score_v3.VARIETY: {**variety, "reads": "states"}}
    )
