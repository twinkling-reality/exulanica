"""The ability modules and what each declares, stated once, as data.

``ability-modules.v1.json`` beside this module is the one statement of which ability modules
exist, by version: the abilities each serves (the abilities catalog's keys whose ``module`` it
names), its bounded parameters, the event kinds its minute records, and whether it is built. Each
row gives a reason for itself and for every parameter.

A parameter with a ``value`` is a figure the module itself uses, the same for every thing it runs
for; one without is supplied by a kind of thing, within the stated bounds
(:meth:`AbilityModule.checked`).

A society of things records, in its first input, the modules it runs, by version, and its minute
runs exactly those (:func:`recorded_modules`). So a module version stays in this table while any
stored society names it, and a new version is a new row beside the last: a society made before it
replays as it was made. A new society records :func:`current_modules`, every built module at its
newest version.

Every lookup goes through :func:`ability_module`, which refuses a module the table does not
state by name, and :func:`built_module`, which also refuses a row that is not built with the
refusal the row states. Pure: no connection, no store, no world. The table is read once per
process.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal

__all__ = [
    "BEFORE_RECORDED",
    "CROSSING",
    "FOLLOW",
    "HANDS",
    "HANDS_FROM_OWN_SIDE",
    "MODULES_PATH",
    "NOTICE",
    "PURPOSEFUL",
    "PURPOSEFUL_BY_KIND",
    "REMEMBER",
    "SAY",
    "AbilityError",
    "AbilityModule",
    "AbilityModuleNotConnected",
    "Parameter",
    "UnknownAbilityModule",
    "ability_module",
    "ability_modules",
    "built_module",
    "current_modules",
    "load_ability_modules",
    "recorded_modules",
    "recorded_row",
]

MODULES_PATH: Final = Path(__file__).with_name("ability-modules.v1.json")
TABLE_PROFILE: Final = "exulanica.ability-modules/v1"
#: The module identities the engine's own code names. Each is a row of the table.
PURPOSEFUL: Final = "exulanica-ability/purposeful/v1"
#: The planner's choices gated by kind: a being does only the routine's activities its kind lists.
PURPOSEFUL_BY_KIND: Final = "exulanica-ability/purposeful/v2"
SAY: Final = "exulanica-ability/say/v1"
CROSSING: Final = "exulanica-ability/crossing/v1"
HANDS: Final = "exulanica-ability/hands/v1"
#: Hands whose being walks up to act on its own side of the thing or the being it acts with.
HANDS_FROM_OWN_SIDE: Final = "exulanica-ability/hands/v2"
FOLLOW: Final = "exulanica-ability/follow/v1"
NOTICE: Final = "exulanica-ability/notice/v1"
REMEMBER: Final = "exulanica-ability/remember/v1"
#: The modules a society of things runs whose first input records none: the ones every society
#: of things ran before inputs recorded them.
BEFORE_RECORDED: Final = (PURPOSEFUL, SAY, CROSSING)

Status = Literal["built", "not_connected"]
_STATUSES: Final = ("built", "not_connected")
_NAME: Final = re.compile(r"exulanica-ability/([a-z][a-z_]*)/v([1-9][0-9]{0,3})")
_ROW_KEYS: Final = frozenset(
    {"abilities", "events", "module", "parameters", "reason", "refusal", "status"}
)
_PARAMETER_KEYS: Final = frozenset({"maximum", "minimum", "name", "reason", "unit", "value"})


class AbilityError(ValueError):
    """An ability module or parameter the table does not admit, named."""


class UnknownAbilityModule(AbilityError):
    """A module identity the table does not state. Named, never treated as a known one."""


class AbilityModuleNotConnected(AbilityError):
    """A module the table states but does not build, with the refusal its row names."""

    def __init__(self, module: str, refusal: str) -> None:
        super().__init__(f"ability module {module!r} is not connected: {refusal}")
        self.module = module
        self.code = refusal


@dataclass(frozen=True, slots=True)
class Parameter:
    """One bounded parameter: inclusive integer bounds, a unit, a reason, and a value or none."""

    name: str
    minimum: int
    maximum: int
    unit: str
    #: The module's own figure, or ``None`` where each kind states one.
    value: int | None
    reason: str

    def admits(self, value: object) -> bool:
        return type(value) is int and self.minimum <= value <= self.maximum


@dataclass(frozen=True, slots=True)
class AbilityModule:
    """One row of the table: one version of one module."""

    module: str
    status: Status
    refusal: str | None
    #: The abilities it serves, the abilities catalog's keys naming it, in the row's order.
    abilities: tuple[str, ...]
    parameters: Mapping[str, Parameter]
    #: The event kinds its minute records.
    events: tuple[str, ...]
    reason: str

    @property
    def name(self) -> str:
        """The module's name without its version: ``hands`` for ``exulanica-ability/hands/v1``."""
        found = _NAME.fullmatch(self.module)
        assert found is not None
        return found.group(1)

    @property
    def version(self) -> int:
        found = _NAME.fullmatch(self.module)
        assert found is not None
        return int(found.group(2))

    def value(self, name: str) -> int:
        """The module's own figure for ``name``; a parameter a kind supplies has none here."""
        parameter = self.parameters.get(name)
        if parameter is None or parameter.value is None:
            raise AbilityError(f"ability module {self.module!r} states no value for {name!r}")
        return parameter.value

    def checked(self, name: str, value: object, *, where: str) -> int:
        """``value`` when the module's bounds admit it, else a refusal naming both."""
        parameter = self.parameters.get(name)
        if parameter is None:
            raise AbilityError(f"ability module {self.module!r} has no parameter {name!r}")
        if not parameter.admits(value):
            raise AbilityError(
                f"{where}: {name} is an int in [{parameter.minimum}, {parameter.maximum}] "
                f"{parameter.unit} for {self.module}, got {value!r}"
            )
        assert type(value) is int
        return value


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise AbilityError(f"{where} is non-empty text")
    return value


def _keys(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and re.fullmatch(r"[a-z][a-z_]*", item) for item in value
    ):
        raise AbilityError(f"{where} is a list of lowercase keys")
    if len(set(value)) != len(value):
        raise AbilityError(f"{where} names a key twice")
    return tuple(value)


def _parameter(row: Any, where: str) -> Parameter:
    if not isinstance(row, dict) or set(row) != _PARAMETER_KEYS:
        raise AbilityError(f"{where} states exactly {sorted(_PARAMETER_KEYS)}")
    minimum, maximum, value = row["minimum"], row["maximum"], row["value"]
    if type(minimum) is not int or type(maximum) is not int or not minimum <= maximum:
        raise AbilityError(f"{where} states integer bounds, minimum at most maximum")
    if value is not None and (type(value) is not int or not minimum <= value <= maximum):
        raise AbilityError(f"{where} states a value inside its bounds, or none")
    return Parameter(
        name=_text(row["name"], f"{where}.name"),
        minimum=minimum,
        maximum=maximum,
        unit=_text(row["unit"], f"{where}.unit"),
        value=value,
        reason=_text(row["reason"], f"{where}.reason"),
    )


def _module(row: Any) -> AbilityModule:
    if not isinstance(row, dict) or set(row) != _ROW_KEYS:
        raise AbilityError(f"an ability module row states exactly {sorted(_ROW_KEYS)}")
    name = _text(row["module"], "module")
    where = f"ability module {name}"
    if _NAME.fullmatch(name) is None:
        raise AbilityError(f"{where} is named exulanica-ability/<name>/v<N>")
    status, refusal = row["status"], row["refusal"]
    if status not in _STATUSES:
        raise AbilityError(f"{where} status is one of {_STATUSES}")
    if (status == "built") != (refusal is None):
        raise AbilityError(f"{where}: a built module has no refusal and any other names one")
    if refusal is not None:
        _text(refusal, f"{where}.refusal")
    if not isinstance(row["parameters"], list):
        raise AbilityError(f"{where}.parameters is a list")
    parameters = [
        _parameter(item, f"{where}.parameters[{index}]")
        for index, item in enumerate(row["parameters"])
    ]
    names = [parameter.name for parameter in parameters]
    if len(set(names)) != len(names):
        raise AbilityError(f"{where} states a parameter twice")
    return AbilityModule(
        module=name,
        status=status,
        refusal=refusal,
        abilities=_keys(row["abilities"], f"{where}.abilities"),
        parameters=MappingProxyType({parameter.name: parameter for parameter in parameters}),
        events=_keys(row["events"], f"{where}.events"),
        reason=_text(row["reason"], f"{where}.reason"),
    )


def load_ability_modules(path: Path = MODULES_PATH) -> Mapping[str, AbilityModule]:
    """Every row of the table at ``path``, by module identity, each checked."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"profile", "modules"}:
        raise AbilityError("the ability module table states exactly its profile and its modules")
    if document["profile"] != TABLE_PROFILE:
        raise AbilityError(f"the ability module table is {TABLE_PROFILE}")
    rows = [_module(row) for row in document["modules"]]
    found = {row.module: row for row in rows}
    if len(found) != len(rows):
        raise AbilityError("the ability module table states a module version twice")
    by_name: dict[str, list[AbilityModule]] = {}
    for row in rows:
        by_name.setdefault(row.name, []).append(row)
    for name, versions in by_name.items():
        numbers = sorted(row.version for row in versions)
        if numbers != list(range(1, len(numbers) + 1)):
            raise AbilityError(f"ability module {name} keeps every version from 1, in order")
    return MappingProxyType(found)


@cache
def ability_modules() -> Mapping[str, AbilityModule]:
    """The table this process reads, once."""
    return load_ability_modules()


def ability_module(module: str) -> AbilityModule:
    """The row ``module`` names, or :class:`UnknownAbilityModule`."""
    found = ability_modules().get(module)
    if found is None:
        raise UnknownAbilityModule(f"no ability module {module!r} is stated")
    return found


def built_module(module: str) -> AbilityModule:
    """The row ``module`` names when it is built, or the refusal its row states."""
    found = ability_module(module)
    if found.status != "built":
        assert found.refusal is not None
        raise AbilityModuleNotConnected(module, found.refusal)
    return found


def current_modules() -> tuple[str, ...]:
    """What a new society of things records: every built module at its newest built version, in
    module order."""
    newest: dict[str, AbilityModule] = {}
    for row in ability_modules().values():
        if row.status != "built":
            continue
        held = newest.get(row.name)
        if held is None or row.version > held.version:
            newest[row.name] = row
    return tuple(sorted(row.module for row in newest.values()))


def recorded_modules(document: Mapping[str, Any]) -> tuple[str, ...]:
    """The modules a society of things runs, as its first input ``document`` records them: the
    ones it names, each a built row of the table, or :data:`BEFORE_RECORDED` where it names none."""
    stated: Sequence[str] | None = document.get("modules")
    if stated is None:
        return BEFORE_RECORDED
    for module in stated:
        built_module(module)
    return tuple(stated)


def recorded_row(modules: Sequence[str], name: str) -> AbilityModule | None:
    """The built row of the module called ``name`` that a society recorded among ``modules``, at the
    version it recorded, or None where it recorded none: its figures are that version's, whatever
    later rows of the same module state."""
    found = [
        built_module(module)
        for module in modules
        if (match := _NAME.fullmatch(module)) is not None and match.group(1) == name
    ]
    if len(found) > 1:
        raise AbilityError(f"a society records one version of the {name} module, not {len(found)}")
    return found[0] if found else None
