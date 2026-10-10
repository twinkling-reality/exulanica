"""A society opens awake: people are on a town's streets, doing something, when it is first shown.

A living town's society is born with everyone at home, so its first minutes show an empty street,
and a society of things is born with every being standing idle with no goal.
:func:`open_awake` advances a society that has just been made, minute by ordinary minute through
the repository's own :meth:`~exulanica.world.society_repository.SocietyRepository.advance` (the
call the steps route makes), until a stated share of its people is outdoors or, where its state
does not say who is indoors, a stated share of its beings is doing something. Every one of those
minutes is stored with its events and replays like any other; no model is asked, since a minute
with no receipt is the routine's alone; nothing about the routine, the engine or the input changes.

It is called where a society is made (:func:`exulanica.api.society_making.make_society`), so the
route a person's page asks and the arrival worlds an installation provisions open the same way,
and a society read back because its version already holds one is never advanced again.

The minutes take the repository's ``advance`` on purpose and not the playback control's manual
step: ``advance`` writes no control receipt, so a control set playing afterwards has advanced no
minute and its next one is due at once. Through the manual step the first Play would wait a whole
interval after the last of these minutes, with nothing for a page to draw meanwhile.

**The rule is data.** ``exulanica/world/society-opening-policy.v2.json`` states the two shares, the
least and the most minutes and the most seconds to spend, each a chosen budget with its reason, and
that the default is on; version 1 of the file, which states one share and no least, stays beside
it and is read by the same loader. A host changes the rule with :data:`SOCIETY_OPENING_ENV`; a
hand-built :class:`~exulanica.api.services.Services` opens nothing.

A state that says for each person whether they are indoors is advanced until the outdoors share
holds, whatever engine keeps it. One that does not, but says for each being what it is doing, is
advanced until the share doing something holds (an action whose kind is not ``idle``), where the
opening states such a share for the family of state its engine keeps: version 2 states it for a
society of things, the one family it is measured for, so a purposeful society, like every society
under version 1's values, is left at its first minute. A state that says neither is always left
as it is.

The seconds are the server's clock, so a busy host would open a town less awake than a quiet one:
the least minutes are advanced before the seconds are counted, unless the share is reached first.
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
    "active_share_milli",
    "open_awake",
    "opening_setting",
    "outdoors_share_milli",
]

#: How a new society opens on this host: absent, the policy file's default; ``off``; ``on`` (the
#: policy's values); or ``share:minutes:seconds`` in the policy's units, such as ``150:60:5``,
#: which may go on ``:least-minutes`` and ``:active-share``, such as ``150:60:5:10:500``. A host
#: that states three numbers states its seconds as the whole wait: its least minutes are 0, and
#: its share of beings doing something is the policy's.
SOCIETY_OPENING_ENV: Final = env_name("SOCIETY_OPENING")

_VALUES: Final = ("outdoors_share_milli", "minutes_maximum", "seconds_maximum")
#: What version 2 of the policy states beside version 1's three.
_VALUES_V2: Final = ("active_share_milli", "minutes_minimum")


class SocietyOpeningRefused(ValueError):
    """The opening setting or policy cannot be read; ``code`` names why."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class SocietyOpening:
    """How far a new society is advanced before it is first shown: until ``outdoors_share_milli``
    thousandths of its people are outdoors or, where its state does not say who is indoors, until
    ``active_share_milli`` thousandths of its beings are doing something; for at most
    ``minutes_maximum`` minutes, and past ``minutes_minimum`` of them for at most
    ``seconds_maximum`` seconds. No minutes is off. The active share is read only for the state
    families ``active_state_families`` names (as the engine table names them); none, or no active
    share (version 1's values), leaves a society whose state does not say who is indoors at its
    first minute."""

    outdoors_share_milli: int
    minutes_maximum: int
    seconds_maximum: int
    active_share_milli: int = 0
    minutes_minimum: int = 0
    active_state_families: frozenset[str] = frozenset()

    @property
    def off(self) -> bool:
        return self.minutes_maximum <= 0


#: Nothing is advanced: what a host that sets ``off`` and a hand-built Services both mean.
OPENING_OFF: Final = SocietyOpening(outdoors_share_milli=0, minutes_maximum=0, seconds_maximum=0)


def _values(
    share: Any,
    minutes: Any,
    seconds: Any,
    where: str,
    *,
    active: Any = 0,
    least: Any = 0,
    families: frozenset[str] = frozenset(),
) -> SocietyOpening:
    stated = zip((*_VALUES, *_VALUES_V2), (share, minutes, seconds, active, least), strict=True)
    for name, value in stated:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SocietyOpeningRefused(
                "society_opening_not_whole_numbers", f"{where} states no whole {name}"
            )
    # No active share is version 1's meaning: such a society is left at its first minute.
    if not 1 <= share <= 1000 or active > 1000:
        raise SocietyOpeningRefused(
            "society_opening_share_out_of_bounds",
            f"{where} states a share of {share if not 1 <= share <= 1000 else active} thousandths,"
            " which is no share of a population",
        )
    return SocietyOpening(
        share,
        minutes,
        seconds,
        active_share_milli=active,
        minutes_minimum=least,
        active_state_families=families if active else frozenset(),
    )


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
    """The policy a file states, or a named refusal: its id, its version (1, or 2 with the share
    of beings doing something and the least minutes), a default of ``on`` or ``off``, the values,
    and a class and a reason for each."""
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
    version = document.get("version")
    if version not in (1, 2):
        raise SocietyOpeningRefused(
            "society_opening_policy_unread", f"{where} states no version this host reads"
        )
    names = _VALUES if version == 1 else (*_VALUES, *_VALUES_V2)
    for name in names:
        if classes.get(name) != "chosen_budget" or not reasons.get(name):
            raise SocietyOpeningRefused(
                "society_opening_policy_unread",
                f"{where} does not class {name} a chosen budget with its reason",
            )
    later: dict[str, Any] = {}
    if version == 2:
        families = document.get("active_share_state_families")
        if (
            not isinstance(families, list)
            or not families
            or not all(isinstance(family, str) and family for family in families)
            or not reasons.get("active_share_state_families")
        ):
            raise SocietyOpeningRefused(
                "society_opening_policy_unread",
                f"{where} does not say, with its reason, which state families the share of"
                " beings doing something is read for",
            )
        later = {
            "active": values.get("active_share_milli"),
            "least": values.get("minutes_minimum"),
            "families": frozenset(families),
        }
    on = _values(*(values.get(name) for name in _VALUES), where, **later)
    if version == 2 and on.active_share_milli < 1:
        raise SocietyOpeningRefused(
            "society_opening_share_out_of_bounds",
            f"{where} states no share of beings doing something",
        )
    return SocietyOpeningPolicy(version=version, on=on, default_on=document["default"] == "on")


#: The policy in force.
SOCIETY_OPENING_POLICY: Final = load_opening_policy(
    Path(__file__).resolve().parents[1] / "world" / "society-opening-policy.v2.json"
)


def opening_setting(
    value: str | None, policy: SocietyOpeningPolicy = SOCIETY_OPENING_POLICY
) -> SocietyOpening:
    """How this host opens a new society, from :data:`SOCIETY_OPENING_ENV`: absent, the policy's
    default; ``off``; ``on``; or ``share:minutes:seconds``, which may go on ``:least-minutes`` and
    ``:active-share``. Anything else is refused by name. Three numbers state the seconds as the
    whole wait (a least of 0 minutes) and take the policy's share of beings doing something; an
    active share of 0 reads no state by what its beings do. Which state families that share is
    read for is the policy's alone."""
    text = (value or "").strip().lower()
    if not text:
        return policy.default
    if text == "off":
        return OPENING_OFF
    if text == "on":
        return policy.on
    parts = text.split(":")
    if len(parts) not in (3, 4, 5) or not all(part.isascii() and part.isdigit() for part in parts):
        raise SocietyOpeningRefused(
            "society_opening_not_recognised",
            f"{SOCIETY_OPENING_ENV} must be absent, off, on or share:minutes:seconds,"
            " with :least-minutes and :active-share after them if stated",
        )
    numbers = [int(part) for part in parts]
    return _values(
        *numbers[:3],
        SOCIETY_OPENING_ENV,
        least=numbers[3] if len(numbers) > 3 else 0,
        active=numbers[4] if len(numbers) > 4 else policy.on.active_share_milli,
        families=policy.on.active_state_families,
    )


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


def active_share_milli(state: Mapping[str, Any]) -> int | None:
    """The share of a state's beings who are doing something, in thousandths: those whose action
    is of a kind other than ``idle``, the state's own word for a being with nothing under way. None
    where the state does not say for every one of them what they are doing (or holds nobody)."""
    people = state.get("inhabitants")
    if not isinstance(people, list) or not people:
        return None
    active = 0
    for person in people:
        action = person.get("action") if isinstance(person, Mapping) else None
        kind = action.get("kind") if isinstance(action, Mapping) else None
        if not isinstance(kind, str) or not kind:
            return None
        active += kind != "idle"
    return 1000 * active // len(people)


def _awake(state: Mapping[str, Any], opening: SocietyOpening, family: str | None) -> bool | None:
    """Whether a state is awake by an opening's shares, or None where it cannot be said: a state
    that says who is indoors is read by the outdoors share alone; one that does not is read by
    the share doing something, where the opening states one for the ``family`` of state it is."""
    outdoors = outdoors_share_milli(state)
    if outdoors is not None:
        return outdoors >= opening.outdoors_share_milli
    if opening.active_share_milli < 1 or family not in opening.active_state_families:
        return None
    active = active_share_milli(state)
    return None if active is None else active >= opening.active_share_milli


def open_awake(
    repository: Any,
    version_id: uuid.UUID,
    snapshot: dict[str, Any],
    opening: SocietyOpening,
    *,
    actor: uuid.UUID | None,
    clock: Callable[[], float] | None = None,
    family: str | None = None,
) -> dict[str, Any]:
    """Advance the society just made, as ``snapshot`` holds it, until ``opening``'s share of its
    people is outdoors or, where its state does not say who is indoors, its share of beings is
    doing something, and answer the snapshot it then holds. ``family`` is the family of state the
    society's engine keeps, as the engine table names it; without it no state is read by what its
    beings do.

    It stops at the first minute the share holds; at ``minutes_maximum`` minutes; past
    ``minutes_minimum`` minutes, once ``seconds_maximum`` seconds have passed on ``clock`` (the
    server's monotonic clock, read between minutes); where the state says neither who is indoors
    nor what each being is doing, or the opening states no share for its family; and where a
    minute is refused because somebody else advanced the society or its world's clock makes it
    wait. The society stands wherever it reached, which is never worse than not having been
    advanced. An opening of no minutes (off) advances nothing.
    """
    read = time.monotonic if clock is None else clock
    started = read()
    for minute in range(opening.minutes_maximum):
        if _awake(snapshot["state"], opening, family) is not False:
            break
        if minute >= opening.minutes_minimum and read() - started >= opening.seconds_maximum:
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
