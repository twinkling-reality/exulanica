"""What to tell a person about a set of photographs, in words a person would use.

A refusal that says ``registered_fraction 0.583 < 0.8`` is a sealed door. This vocabulary is the
other half of the verdict: each entry leads with what the person gets, says what was measured
about this particular set, and says what to do in a sentence someone would say out loud.

Three rules hold for every entry.

*   **Closed.** An instruction is one of the keys below, never free text, so a fault nobody
    anticipated raises instead of arriving as a sentence nobody reviewed.
*   **Only measured numbers.** Every number in a sentence is a count the graph produced for this
    set and is passed in by name. No template carries a number of its own.
*   **Never a photograph count as the requirement.** The measurement that decides this lane is
    that overlap decides and count does not: twelve photographs rebuilt a rock at one spacing and
    failed at another. So the advice is always to take one every few steps so each photograph
    overlaps the one before it, and never to take some number of photographs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

__all__ = [
    "INSTRUCTION_KEYS",
    "INSTRUCTION_VOCABULARY",
    "Instruction",
    "InstructionKey",
    "instruction",
]

INSTRUCTION_VOCABULARY: Final = "exulanica.capture-instructions/v1"

InstructionKey = Literal[
    "too_few_photographs",
    "no_overlapping_neighbours",
    "separate_groups",
    "mostly_unconnected",
    "some_unconnected",
    "one_side_uncovered",
    "unreadable_photographs",
    "run_placed_none",
    "run_placed_some",
]

_KEPT: Final = "Your photographs are kept here as they are."
_NOT_YET: Final = f"{_KEPT} They won't build into a 3D place yet."
_WALK: Final = (
    "Walk around it and take one every few steps, so each photograph overlaps the one before it."
)


@dataclass(frozen=True, slots=True)
class _Entry:
    counts: tuple[str, ...]
    headline: str
    detail: str
    action: str | None


_ENTRIES: Final[dict[InstructionKey, _Entry]] = {
    # The set is too small to form any pair at all.
    "too_few_photographs": _Entry(
        ("photographs",),
        _NOT_YET,
        "There {photographs_are}, and a place is built from photographs that overlap one another.",
        _WALK,
    ),
    # Neighbouring photographs are too far apart end to end.
    "no_overlapping_neighbours": _Entry(
        ("photographs",),
        _NOT_YET,
        "None of these {photographs_noun} shares enough with any other: they were taken too far "
        "apart.",
        _WALK,
    ),
    # Two or more islands with nothing bridging them.
    "separate_groups": _Entry(
        ("groups",),
        _NOT_YET,
        "These photographs fall into {groups} separate groups, and nothing joins one group to "
        "the next.",
        "Go back to the gaps between the groups and take one every few steps, so each photograph "
        "overlaps the one before it.",
    ),
    # One group, and too many photographs outside it for the set to be placed.
    "mostly_unconnected": _Entry(
        ("largest", "photographs", "others"),
        _NOT_YET,
        "Only {largest} of these {photographs_noun} overlap one another. {others_rest} overlap "
        "anything, so too few of them would be placed together.",
        "Take more between them, one every few steps, so each photograph overlaps the one before "
        "it.",
    ),
    # A buildable set with photographs that will be left out of it.
    "some_unconnected": _Entry(
        ("others",),
        "Most of these photographs should build into a 3D place.",
        "{others_count} of them {others_verb} overlap anything, so {others_pronoun} won't be in "
        "it.",
        "To include {others_pronoun}, take more around {others_pronoun}, one every few steps, so "
        "each photograph overlaps the one before it.",
    ),
    # One side of the subject has no coverage. In the vocabulary so the shape has words, and
    # emitted by NO current policy: overlap-policy/v1 tried to read it from the pair graph, and
    # its readings of turntable arcs of known extent were wrong too often and moved with the
    # decoder, so it does not claim it. A later policy that can measure it, from a pose
    # receipt's cameras for instance, has the sentence ready.
    "one_side_uncovered": _Entry(
        (),
        "These photographs should build into a 3D place, but not all the way round.",
        "They form one line whose two ends don't meet, so whatever lies between the ends isn't "
        "covered.",
        "To include it, keep walking round and take one every few steps until you're back where "
        "you started.",
    ),
    "unreadable_photographs": _Entry(
        ("unreadable",),
        "Some of these photographs couldn't be used.",
        "{unreadable_count} of them couldn't be read, so {unreadable_clause} compared with the "
        "others.",
        None,
    ),
    # A run's own receipt, read back as a reason.
    "run_placed_none": _Entry(
        ("photographs",),
        f"{_KEPT} A rebuild was tried and didn't make a 3D place.",
        "None of the {photographs_noun} could be placed together.",
        _WALK,
    ),
    "run_placed_some": _Entry(
        ("registered", "photographs"),
        f"{_KEPT} A rebuild was tried and didn't make a 3D place.",
        "Only {registered} of the {photographs_noun} could be placed together, which isn't "
        "enough to build it.",
        _WALK,
    ),
}

INSTRUCTION_KEYS: Final[tuple[InstructionKey, ...]] = tuple(_ENTRIES)


@dataclass(frozen=True, slots=True)
class Instruction:
    """One rendered instruction. ``action`` is None when there is nothing to do about it."""

    key: InstructionKey
    headline: str
    detail: str
    action: str | None

    def record(self) -> dict[str, str | None]:
        return {
            "key": self.key,
            "headline": self.headline,
            "detail": self.detail,
            "action": self.action,
        }


def _noun(count: int) -> str:
    return f"{count} photograph" if count == 1 else f"{count} photographs"


def instruction(key: InstructionKey, counts: Mapping[str, int]) -> Instruction:
    """Render one instruction from its key and the counts the graph measured for this set.

    Refuses a key outside the vocabulary, a missing or extra count, and a count that is not a
    non-negative integer. A sentence cannot be built from a number nobody measured.
    """
    entry = _ENTRIES.get(key)
    if entry is None:
        raise KeyError(f"{key!r} is not in {INSTRUCTION_VOCABULARY}")
    if set(counts) != set(entry.counts):
        raise ValueError(f"{key} takes exactly {sorted(entry.counts)}, got {sorted(counts)}")
    for name, value in counts.items():
        if type(value) is not int or value < 0:
            raise ValueError(f"{key}: {name} must be a non-negative int")
    words: dict[str, object] = dict(counts)
    if "photographs" in counts:
        total = counts["photographs"]
        words["photographs_noun"] = _noun(total)
        words["photographs_are"] = (
            "are no photographs here"
            if total == 0
            else "is only one photograph"
            if total == 1
            else f"are {total} photographs"
        )
    if "others" in counts:
        others = counts["others"]
        words["others_count"] = "One" if others == 1 else str(others)
        words["others_verb"] = "doesn't" if others == 1 else "don't"
        words["others_pronoun"] = "it" if others == 1 else "them"
        words["others_rest"] = (
            "The other one doesn't" if others == 1 else f"The other {others} don't"
        )
    if "unreadable" in counts:
        unreadable = counts["unreadable"]
        words["unreadable_count"] = "One" if unreadable == 1 else str(unreadable)
        words["unreadable_clause"] = "it wasn't" if unreadable == 1 else "they weren't"
    return Instruction(
        key=key,
        headline=entry.headline.format(**words),
        detail=entry.detail.format(**words),
        action=entry.action.format(**words) if entry.action is not None else None,
    )
