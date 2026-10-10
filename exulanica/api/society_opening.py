"""A society opens awake: people are on a town's streets when the town is first shown.

A living town's society is born with everyone at home, so its first minutes show an empty street.
:func:`open_awake` advances a society that has just been made, minute by ordinary minute through
the repository's own :meth:`~exulanica.world.society_repository.SocietyRepository.advance` (the
call the steps route makes), until a stated share of its people is outdoors. Every one of those
minutes is stored with its events and replays like any other; no model is asked, since a minute
with no receipt is the routine's alone; nothing about the routine, the engine or the input changes.

It is called where a society is made (:func:`exulanica.api.society_making.make_society`), so the
route a person's page asks and the arrival worlds an installation provisions open the same way,
and a society read back because its version already holds one is never advanced again.

The minutes take the repository's ``advance`` on purpose and not the playback control's manual
step: ``advance`` writes no control receipt, so a control set playing afterwards has advanced no
minute and its next one is due at once. Through the manual step the first Play would wait a whole
interval after the last of these minutes, with nothing for a page to draw meanwhile.

**The rule is data.** ``exulanica/world/society-opening-policy.v1.json`` states the share to reach,
the most minutes and the most seconds to spend, each a chosen budget with its reason, and that the
default is on. A host changes it with :data:`SOCIETY_OPENING_ENV`; a hand-built
:class:`~exulanica.api.services.Services` opens nothing.

It reads the state, not an engine's name: a state that says for each person whether they are
indoors is advanced until the share is outdoors, and one that does not (a society of things, a
starter's society) is left at its first minute.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from exulanica.env import env_name
from exulanica.world.society import StaleSocietyState
from exulanica.world.world_clock import ClockRefused

__all__ = [
    "OPENING_OFF",
    "SOCIETY_OPENING_ENV",
    "SOCIETY_OPENING_POLICY",
    "SocietyOpening",
    "SocietyOpeningRefused",
    "open_awake",
    "opening_setting",
    "outdoors_share_milli",
]

#: How a new society opens on this host: absent, the policy file's default; ``off``; ``on`` (the
#: policy's values); or ``share:minutes:seconds`` in the policy's units, such as ``150:60:5``.
SOCIETY_OPENING_ENV: Final = env_name("SOCIETY_OPENING")

_VALUES: Final = ("outdoors_share_milli", "minutes_maximum", "seconds_maximum")


class SocietyOpeningRefused(ValueError):
    """The opening setting or policy cannot be read; ``code`` names why."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class SocietyOpening:
    """How far a new society is advanced before it is first shown: until ``outdoors_share_milli``
    thousandths of its people are outdoors, for at most ``minutes_maximum`` minutes and
    ``seconds_maximum`` seconds. No minutes is off."""

    outdoors_share_milli: int
    minutes_maximum: int
    seconds_maximum: int

    @property
    def off(self) -> bool:
        return self.minutes_maximum <= 0


#: Nothing is advanced: what a host that sets ``off`` and a hand-built Services both mean.
OPENING_OFF: Final = SocietyOpening(outdoors_share_milli=0, minutes_maximum=0, seconds_maximum=0)


def _values(share: Any, minutes: Any, seconds: Any, where: str) -> SocietyOpening:
    for name, value in zip(_VALUES, (share, minutes, seconds), strict=True):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SocietyOpeningRefused(
                "society_opening_not_whole_numbers", f"{where} states no whole {name}"
            )
    if not 1 <= share <= 1000:
        raise SocietyOpeningRefused(
            "society_opening_share_out_of_bounds",
            f"{where} states a share of {share} thousandths, which is no share of a population",
        )
    return SocietyOpening(share, minutes, seconds)


@dataclass(frozen=True, slots=True)
class SocietyOpeningPolicy:
    """The opening policy as its file states it: what ``on`` means, and whether a host that says
    nothing opens its societies."""

    version: int
    on: SocietyOpening
    default_on: bool

    @property
    def default(self) -> SocietyOpening:
        return self.on if self.default_on else OPENING_OFF


def load_opening_policy(path: Path) -> SocietyOpeningPolicy:
    """The policy a file states, or a named refusal: its id, a default of ``on`` or ``off``, the
    three values, and a class and a reason for each."""
    document = json.loads(path.read_text(encoding="utf-8"))
    where = path.name
    if document.get("policy_id") != "exulanica.society-opening":
        raise SocietyOpeningRefused("society_opening_policy_unread", f"{where} is another policy")
    values, reasons, classes = (document.get(key) for key in ("values", "reasons", "classes"))
    if not all(isinstance(part, Mapping) for part in (values, reasons, classes)):
        raise SocietyOpeningRefused(
            "society_opening_policy_unread", f"{where} states no values, classes or reasons"
        )
    if document.get("default") not in ("on", "off") or not reasons.get("default"):
        raise SocietyOpeningRefused(
            "society_opening_policy_unread", f"{where} states no default with its reason"
        )
    for name in _VALUES:
        if classes.get(name) != "chosen_budget" or not reasons.get(name):
            raise SocietyOpeningRefused(
                "society_opening_policy_unread",
                f"{where} does not class {name} a chosen budget with its reason",
            )
    return SocietyOpeningPolicy(
        version=int(document["version"]),
        on=_values(*(values.get(name) for name in _VALUES), where),
        default_on=document["default"] == "on",
    )


#: The policy in force.
SOCIETY_OPENING_POLICY: Final = load_opening_policy(
    Path(__file__).resolve().parents[1] / "world" / "society-opening-policy.v1.json"
)


def opening_setting(
    value: str | None, policy: SocietyOpeningPolicy = SOCIETY_OPENING_POLICY
) -> SocietyOpening:
    """How this host opens a new society, from :data:`SOCIETY_OPENING_ENV`: absent, the policy's
    default; ``off``; ``on``; or ``share:minutes:seconds``. Anything else is refused by name."""
    text = (value or "").strip().lower()
    if not text:
        return policy.default
    if text == "off":
        return OPENING_OFF
    if text == "on":
        return policy.on
    parts = text.split(":")
    if len(parts) != 3 or not all(part.isascii() and part.isdigit() for part in parts):
        raise SocietyOpeningRefused(
            "society_opening_not_recognised",
            f"{SOCIETY_OPENING_ENV} must be absent, off, on or share:minutes:seconds",
        )
    return _values(*(int(part) for part in parts), SOCIETY_OPENING_ENV)


def outdoors_share_milli(state: Mapping[str, Any]) -> int | None:
    """The share of a state's people who are outdoors, in thousandths, or None where the state
    does not say for every one of them whether they are indoors (or holds nobody)."""
    people = state.get("inhabitants")
    if not isinstance(people, list) or not people:
        return None
    outdoors = 0
    for person in people:
        location = person.get("location") if isinstance(person, Mapping) else None
        indoors = location.get("indoors") if isinstance(location, Mapping) else None
        if not isinstance(indoors, bool):
            return None
        outdoors += not indoors
    return 1000 * outdoors // len(people)


def open_awake(
    repository: Any,
    version_id: uuid.UUID,
    snapshot: dict[str, Any],
    opening: SocietyOpening,
    *,
    actor: uuid.UUID | None,
    clock: Callable[[], float] | None = None,
) -> dict[str, Any]:
    """Advance the society just made, as ``snapshot`` holds it, until ``opening``'s share of its
    people is outdoors, and answer the snapshot it then holds.

    It stops at the first minute the share holds, at ``minutes_maximum`` minutes, once
    ``seconds_maximum`` seconds have passed on ``clock`` (the server's monotonic clock, read
    between minutes), where the state does not say who is indoors, and where a minute is refused
    because somebody else advanced the society or its world's clock makes it wait: the society
    stands wherever it reached, which is never worse than not having been advanced. An opening
    of no minutes (off) advances nothing.
    """
    read = time.monotonic if clock is None else clock
    started = read()
    for _ in range(opening.minutes_maximum):
        share = outdoors_share_milli(snapshot["state"])
        if share is None or share >= opening.outdoors_share_milli:
            break
        if read() - started >= opening.seconds_maximum:
            break
        try:
            snapshot = repository.advance(
                version_id,
                base_tick=snapshot["current_tick"],
                base_state_sha256=snapshot["state_sha256"],
                actor=actor,
            )
        except (StaleSocietyState, ClockRefused):
            break
    return snapshot
