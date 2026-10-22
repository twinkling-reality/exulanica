"""The settings a running instance reads from its environment at startup.

Each is named here with what it means and how it is read, and a value that is none of its forms is
refused at startup by name (:class:`SocietySettingRefused`) rather than read as something else.
:mod:`exulanica.api.services` reads them when it wires an instance and names them too, so a caller
that imports a setting from there keeps working.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from typing import Final, Literal

from exulanica.api.society_opening import (
    SOCIETY_OPENING_ENV,
    SocietyOpening,
    SocietyOpeningRefused,
    opening_setting,
)
from exulanica.env import env_get, env_name
from exulanica.world.draft_policy import current_world_draft_policy
from exulanica.world.society_controls import (
    BASE_TICK_INTERVAL_DIVISOR,
    BASE_TICK_INTERVAL_MAX_MS,
    BASE_TICK_INTERVAL_MIN_MS,
    DEFAULT_BASE_TICK_INTERVAL_MS,
    validate_settings,
)
from exulanica.world.society_minute_cost import COST_SCALE_UNIT_MILLI

#: The connection string the Selection executor uses. Optional, and its absence is reported.
READONLY_DATABASE_URL_ENV: Final = env_name("READONLY_DATABASE_URL")

#: Where the content-addressed store lives. The same directory the ingest CLI writes.
DATA_DIR_ENV: Final = env_name("DATA_DIR")

#: Set to ``0``, ``false`` or ``off`` to serve the API without draining the derivative queue in
#: this process. Anything else, including absence, runs it: an instance serving ``POST /intake``
#: with nothing draining the queue is an upload that never finishes, and that is the wrong
#: default to arrive at by saying nothing.
DERIVATIVE_WORKER_ENV: Final = env_name("DERIVATIVE_WORKER")

#: Account-wide society playback remains off unless the host opts in. Static
#: ``society_control_workspaces`` remain an independent, narrower enablement path.
SOCIETY_CONTROL_WORKER_ENV: Final = env_name("SOCIETY_CONTROL_WORKER")

#: A JSON array of workspace ids whose playing societies this instance advances, with no
#: accounts. Absent or ``[]`` plays none. Independent of the account-wide switch above.
SOCIETY_CONTROL_WORKSPACES_ENV: Final = env_name("SOCIETY_CONTROL_WORKSPACES")

#: Who plays the societies this host plays (the listed and discovered workspaces above) and seals
#: their coupled traffic. Absent (or an explicit on), this process, in threads. ``process``, a
#: process of its own (``exulanica-playback-worker``), and this one serves the playback controls
#: without playing; ``0``, ``false``, ``off`` or ``no``, nobody, and a society advances only a
#: minute at a time when somebody advances it.
PLAYBACK_WORKER_ENV: Final = env_name("PLAYBACK_WORKER")

#: How many workspaces' claims one playback round runs at once, 1 to 8. Absent means 1: each claim
#: in turn, the behaviour before the setting existed. More lets one workspace's model answers be
#: awaited while another's are; asks stay bounded by the process's model slots either way.
PLAYBACK_WORKERS_ENV: Final = env_name("PLAYBACK_WORKERS")

#: Who plays the comparisons started from the application, for the workspaces this host asks models
#: for. Absent (or an explicit on), this process, in a thread. ``process``, a process of its own
#: (``python -m exulanica.orchestration.comparison_worker``), and this one only serves starts.
#: ``0``, ``false``, ``off`` or ``no``, nobody, and every start is refused
#: (``comparisons_not_played``), since a start nothing plays would hold its world until the end.
COMPARISON_WORKER_ENV: Final = env_name("COMPARISON_WORKER")

#: The base wait between simulated minutes, in whole milliseconds, within the bounds
#: ``exulanica.world.society_controls`` declares. Absent means its declared default.
SOCIETY_TICK_INTERVAL_MS_ENV: Final = env_name("SOCIETY_TICK_INTERVAL_MS")
#: How this host's machine compares with the machines a society's minute was measured on (the
#: society ground catalog's ``minute_cost``): a positive decimal with at most three places, such
#: as ``2`` for a machine twice as slow or ``0.5`` for one twice as fast. One deployment's own
#: figure, from a measurement on its machine; absent means 1, the measured machine.
SOCIETY_MINUTE_COST_SCALE_ENV: Final = env_name("MINUTE_COST_SCALE")

#: Every way a society setting is refused at startup, by the name the refusal carries.
SOCIETY_SETTING_REFUSALS: Final = {
    "society_control_worker_not_boolean": "must be an explicit boolean",
    "society_of_things_not_boolean": "must be an explicit boolean",
    "kinds_from_people_not_boolean": "must be an explicit boolean",
    "personal_install_not_boolean": "must be an explicit boolean",
    "worlds_on_land_not_boolean": "must be an explicit boolean",
    "society_control_workspaces_not_json": "must be a JSON array of workspace ids",
    "society_control_workspaces_not_array": "must be a JSON array of workspace ids",
    "society_control_workspaces_not_uuid": "names an entry that is not a workspace id",
    "society_control_workspaces_duplicate": "names a workspace more than once",
    "society_tick_interval_not_integer": "must be a whole number of milliseconds",
    "minute_cost_scale_not_decimal": (
        "must be a positive decimal with at most three places, such as 1, 2.5 or 0.75"
    ),
    "society_opening_not_recognised": (
        "must be absent, off, on or share:minutes:seconds, with :least-minutes and"
        " :active-share after them if stated"
    ),
    "society_opening_not_whole_numbers": "must state whole numbers",
    "society_opening_share_out_of_bounds": "must state a share from 1 to 1000 thousandths",
    "comparison_worker_not_recognised": "must be absent, on, process or off",
    "playback_worker_not_recognised": "must be absent, on, process or off",
    "playback_workers_out_of_bounds": "must be absent or a whole number from 1 to 8",
    "society_tick_interval_out_of_bounds": (
        f"must be {BASE_TICK_INTERVAL_MIN_MS} to {BASE_TICK_INTERVAL_MAX_MS} milliseconds and "
        f"divisible by {BASE_TICK_INTERVAL_DIVISOR}, so every speed divides it exactly"
    ),
}


class SocietySettingRefused(ValueError):
    """A society setting in the environment that startup refuses, named by ``code``."""

    def __init__(self, code: str, variable: str) -> None:
        super().__init__(f"{code}: {variable} {SOCIETY_SETTING_REFUSALS[code]}")
        self.code = code
        self.variable = variable


#: A JSON file of host registrations for saved worlds, each naming the place its society binds.
#: Optional: a person can bring inhabitants into a saved world of their own without one, and the
#: society then binds a place derived from the world itself. A registration here takes
#: precedence for the version it names. Nothing is ever registered or created by saving a world;
#: a society exists only once somebody asks for it.
SOCIETY_AUTHORED_WORLDS_ENV: Final = env_name("SOCIETY_AUTHORED_WORLDS")
#: Whether a world's owner may make a society of things through the routes. A society made is one
#: every later version of its engine must keep replaying, so a shared server makes none unless it is
#: set on; a personal install (:data:`PERSONAL_INSTALL_ENV`) makes them unless it is set off.
SOCIETY_OF_THINGS_ENV: Final = env_name("SOCIETY_OF_THINGS")
#: Whether the routes take a kind of place from a person and keep its document: drafted from
#: their words (``POST /worlds/drafts``, ``POST /worlds/kinds/drafts``) or written by them
#: (``POST /worlds/kinds``). Off unless it is set on. The document is the person's own and is kept
#: in rows no removal reaches, so a deployment states this only where it can be destroyed again.
KINDS_FROM_PEOPLE_ENV: Final = env_name("KINDS_FROM_PEOPLE")
#: Whether this instance is a person's own install on their own computer (the acceptance launcher's
#: ``--personal``), where every configured token is that person's own: off unless it is set on. A
#: personal install plays the workspaces its tokens may write when
#: ``EXULANICA_SOCIETY_CONTROL_WORKSPACES`` lists none, and makes a society of things unless
#: ``EXULANICA_SOCIETY_OF_THINGS`` is set off. A shared server leaves it off and states both.
PERSONAL_INSTALL_ENV: Final = env_name("PERSONAL_INSTALL")
#: Whether a place made from a sentence stands on land chosen from its words (a land recipe,
#: :mod:`exulanica.world.land_choice`), or on level ground as a place made before it does. On
#: unless it is set off.
WORLDS_ON_LAND_ENV: Final = env_name("WORLDS_ON_LAND")


def _style_pack_uploads(environ: Mapping[str, str]) -> bool:
    """Whether ``EXULANICA_WORKSPACE_STYLE_PACK_UPLOADS`` turns style pack uploads on: ``on``, or
    off when absent; any other value is refused at startup rather than read as either."""
    raw = (env_get("WORKSPACE_STYLE_PACK_UPLOADS", environ) or "off").strip()
    if raw not in ("on", "off"):
        raise ValueError("EXULANICA_WORKSPACE_STYLE_PACK_UPLOADS is on or off")
    return raw == "on"


def _playback_player(value: str | None) -> Literal["here", "process", "none"]:
    """Who plays this host's societies (``EXULANICA_PLAYBACK_WORKER``): ``here``, ``process`` or
    ``none``, or a named refusal of anything else."""
    normalized = (value or "").strip().lower()
    if normalized in ("", "1", "true", "on", "yes"):
        return "here"
    if normalized == "process":
        return "process"
    if normalized in ("0", "false", "off", "no"):
        return "none"
    raise SocietySettingRefused("playback_worker_not_recognised", PLAYBACK_WORKER_ENV)


def _comparison_player(value: str | None) -> str:
    """Who plays the comparisons started from the application (``EXULANICA_COMPARISON_WORKER``):
    ``here``, ``process`` or ``none``, or a named refusal of anything else."""
    normalized = (value or "").strip().lower()
    if normalized in ("", "1", "true", "on", "yes"):
        return "here"
    if normalized == "process":
        return "process"
    if normalized in ("0", "false", "off", "no"):
        return "none"
    raise SocietySettingRefused("comparison_worker_not_recognised", COMPARISON_WORKER_ENV)


def _enabled(value: str | None) -> bool:
    """Absent means on. Only an explicit off is off, and it has to be spelled like one."""
    return (value or "").strip().lower() not in ("0", "false", "off", "no")


def _kinds_from_people(environ: Mapping[str, str] | None) -> bool:
    """Whether this instance keeps a kind of place from a person, or a named refusal. The draft
    budgets a deployment states are read here too, once, so a figure that is no whole number
    stops the start by name instead of failing the first request that asks for it."""
    current_world_draft_policy().check(environ)
    return _explicitly_enabled(
        env_get("KINDS_FROM_PEOPLE", environ),
        "kinds_from_people_not_boolean",
        KINDS_FROM_PEOPLE_ENV,
    )


def _explicitly_enabled(
    value: str | None,
    code: str = "society_control_worker_not_boolean",
    variable: str = SOCIETY_CONTROL_WORKER_ENV,
) -> bool:
    """Parse an opt-in switch; absence and explicit false are both safely off. Anything else is
    refused by ``code``, naming the setting ``variable``."""
    normalized = (value or "").strip().lower()
    if normalized in ("", "0", "false", "off", "no"):
        return False
    if normalized in ("1", "true", "on", "yes"):
        return True
    raise SocietySettingRefused(code, variable)


def _personal_install(value: str | None) -> bool:
    """Whether this instance is a person's own install (:data:`PERSONAL_INSTALL_ENV`), or a named
    refusal. Absence is a shared server's answer: off."""
    return _explicitly_enabled(value, "personal_install_not_boolean", PERSONAL_INSTALL_ENV)


def _societies_of_things(value: str | None, *, personal: bool) -> bool:
    """Whether the routes make a society of things (:data:`SOCIETY_OF_THINGS_ENV`), or a named
    refusal: as stated, and when it is absent, on for a personal install and off for any other."""
    if value is None or not value.strip():
        return personal
    return _explicitly_enabled(value, "society_of_things_not_boolean", SOCIETY_OF_THINGS_ENV)


def _worlds_on_land(value: str | None) -> bool:
    """Whether a place made from a sentence stands on land (:data:`WORLDS_ON_LAND_ENV`), or a
    named refusal: on when it is absent or empty, off only where it is stated off, and any other
    value refused rather than read as either."""
    if value is None or not value.strip():
        return True
    return _explicitly_enabled(value, "worlds_on_land_not_boolean", WORLDS_ON_LAND_ENV)


def _society_control_workspaces(value: str | None) -> tuple[uuid.UUID, ...]:
    """The workspaces this instance plays without accounts, or a named refusal.

    Absence plays none. Anything present must be exactly a JSON array of distinct workspace ids:
    an instance that half-read a list it was given would play some worlds and silently not others.
    """
    if value is None or not value.strip():
        return ()
    try:
        document = json.loads(value)
    except json.JSONDecodeError:
        raise SocietySettingRefused(
            "society_control_workspaces_not_json", SOCIETY_CONTROL_WORKSPACES_ENV
        ) from None
    if not isinstance(document, list):
        raise SocietySettingRefused(
            "society_control_workspaces_not_array", SOCIETY_CONTROL_WORKSPACES_ENV
        )
    workspaces: list[uuid.UUID] = []
    for entry in document:
        try:
            if not isinstance(entry, str):
                raise ValueError(entry)
            workspaces.append(uuid.UUID(entry))
        except ValueError:
            raise SocietySettingRefused(
                "society_control_workspaces_not_uuid", SOCIETY_CONTROL_WORKSPACES_ENV
            ) from None
    if len(set(workspaces)) != len(workspaces):
        raise SocietySettingRefused(
            "society_control_workspaces_duplicate", SOCIETY_CONTROL_WORKSPACES_ENV
        )
    return tuple(workspaces)


def _playback_workers(value: str | None) -> int:
    """How many workspaces' claims a playback round runs at once (:data:`PLAYBACK_WORKERS_ENV`),
    1 when absent, or a named refusal of anything but a whole number from 1 to 8."""
    if value is None or not value.strip():
        return 1
    text = value.strip()
    if not text.isascii() or not text.isdigit() or not 1 <= int(text) <= 8:
        raise SocietySettingRefused("playback_workers_out_of_bounds", PLAYBACK_WORKERS_ENV)
    return int(text)


def _society_opening(value: str | None) -> SocietyOpening:
    """How this host opens a society that is made, or a named refusal. Absence is the opening
    policy's own default, read from its file and never restated here."""
    try:
        return opening_setting(value)
    except SocietyOpeningRefused as refused:
        raise SocietySettingRefused(refused.code, SOCIETY_OPENING_ENV) from None


def _society_tick_interval_ms(value: str | None) -> int:
    """The host's base wait between simulated minutes, or a named refusal.

    Absence is the declared default. The bounds are the playback module's own, asked rather than
    restated, so a control saved under this base is one that module accepts.
    """
    if value is None or not value.strip():
        return DEFAULT_BASE_TICK_INTERVAL_MS
    text = value.strip()
    if not text.isascii() or not text.isdigit():
        raise SocietySettingRefused(
            "society_tick_interval_not_integer", SOCIETY_TICK_INTERVAL_MS_ENV
        )
    interval = int(text)
    try:
        validate_settings("paused", 1, interval)
    except ValueError:
        raise SocietySettingRefused(
            "society_tick_interval_out_of_bounds", SOCIETY_TICK_INTERVAL_MS_ENV
        ) from None
    return interval


_COST_SCALE: Final = re.compile(r"(\d+)(?:\.(\d{1,3}))?")


def _minute_cost_scale_milli(value: str | None) -> int:
    """The host's minute cost scale in thousandths, or a named refusal. Absence is the measured
    machine. Read as written, digit by digit, so no host rounds another's figure."""
    if value is None or not value.strip():
        return COST_SCALE_UNIT_MILLI
    stated = _COST_SCALE.fullmatch(value.strip()) if value.strip().isascii() else None
    milli = (
        0
        if stated is None
        else int(stated[1]) * COST_SCALE_UNIT_MILLI + int((stated[2] or "").ljust(3, "0"))
    )
    if milli < 1:
        raise SocietySettingRefused("minute_cost_scale_not_decimal", SOCIETY_MINUTE_COST_SCALE_ENV)
    return milli
