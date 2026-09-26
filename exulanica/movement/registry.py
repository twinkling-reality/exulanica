"""The movement modules and what each declares, stated once, as data.

``movement-modules.v1.json`` beside this module is the one statement of which kinds of movement
exist and, for each, the space it moves in, the catalog its agents come from, its clock, the
bounded parameters every kind's value is checked against, the output it hands a renderer, and
whether it is built. Each row gives a reason for itself and for every parameter.

A parameter with a ``value`` is a figure the module itself uses, the same for every agent it
moves; one without is supplied by a kind of the module's catalog and must fall inside the stated
bounds, which :meth:`MovementModule.checked` enforces for every value a catalog states.

Every lookup of a module goes through :func:`movement_module`, which refuses a module the table
does not state by name, and :func:`built_module`, which also refuses a row that is not built with
the refusal the row states. Nothing guesses that an unknown module behaves like a known one.

Pure: no connection, no store, no world. The table is read once per process.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal

__all__ = [
    "FLIGHT",
    "MODULES",
    "MODULES_PATH",
    "ROADS",
    "WALKING",
    "MovementError",
    "MovementModule",
    "MovementModuleNotConnected",
    "Parameter",
    "ParameterOutOfBounds",
    "UnknownMovementModule",
    "UnknownParameter",
    "built_module",
    "load_movement_modules",
    "movement_module",
]

MODULES_PATH: Final = Path(__file__).with_name("movement-modules.v1.json")
TABLE_PROFILE: Final = "exulanica.movement-modules/v1"
#: The module identities this package's own code names. Each is a row of the table, and a test
#: holds the code's step table to the rows that are built.
WALKING: Final = "exulanica-movement/walking/v1"
FLIGHT: Final = "exulanica-movement/flight/v1"
ROADS: Final = "exulanica-movement/roads/v1"

Status = Literal["built", "not_connected"]
_STATUSES: Final = ("built", "not_connected")
_SPACES: Final = ("air-volume", "ground-lattice", "road-graph")
_CLOCKS: Final = ("host", "page", "society")
_ROW_KEYS: Final = frozenset(
    {"agents", "clock", "module", "output", "parameters", "reason", "refusal", "space", "status"}
)
_PARAMETER_KEYS: Final = frozenset({"maximum", "minimum", "name", "reason", "unit", "value"})


class MovementError(ValueError):
    """A movement module or parameter the table does not admit, named."""


class UnknownMovementModule(MovementError):
    """A module identity the table does not state. Named, never treated as a known one."""


class MovementModuleNotConnected(MovementError):
    """A module the table states but does not build, with the refusal its row names."""

    def __init__(self, module: str, refusal: str) -> None:
        super().__init__(f"movement module {module!r} is not connected: {refusal}")
        self.module = module
        self.code = refusal


class UnknownParameter(MovementError):
    """A parameter name a module does not declare."""


class ParameterOutOfBounds(MovementError):
    """A value outside the bounds a module declares for it."""


@dataclass(frozen=True, slots=True)
class Parameter:
    """One bounded parameter: inclusive integer bounds, a unit, a reason, and a value or none."""

    name: str
    minimum: int
    maximum: int
    unit: str
    #: The module's own figure, or ``None`` where each kind of its catalog states one.
    value: int | None
    reason: str

    def admits(self, value: object) -> bool:
        return type(value) is int and self.minimum <= value <= self.maximum


@dataclass(frozen=True, slots=True)
class MovementModule:
    """One row of the table."""

    module: str
    status: Status
    refusal: str | None
    space_kind: str
    space_profiles: tuple[str, ...]
    agents_catalog: str
    #: The agent kinds it moves, or ``None`` where every kind of its catalog is moved by it.
    agents_kinds: tuple[str, ...] | None
    clock_kind: str
    step_ms: int
    output_profile: str
    parameters: Mapping[str, Parameter]
    reason: str

    def parameter(self, name: str) -> Parameter:
        found = self.parameters.get(name)
        if found is None:
            raise UnknownParameter(f"movement module {self.module!r} has no parameter {name!r}")
        return found

    def value(self, name: str) -> int:
        """The module's own figure for ``name``; a parameter a kind supplies has none here."""
        stated = self.parameter(name).value
        if stated is None:
            raise UnknownParameter(
                f"movement module {self.module!r} states no value for {name!r}; a kind supplies it"
            )
        return stated

    def admits(self, name: str, value: object) -> bool:
        return self.parameter(name).admits(value)

    def checked(self, name: str, value: object, *, where: str) -> int:
        """``value`` when the module's bounds admit it, else a refusal naming both."""
        parameter = self.parameter(name)
        if not parameter.admits(value):
            raise ParameterOutOfBounds(
                f"{where}: {name} is an int in [{parameter.minimum}, {parameter.maximum}] "
                f"{parameter.unit} for {self.module}, got {value!r}"
            )
        assert type(value) is int
        return value

    def supplied(self) -> tuple[str, ...]:
        """The parameters each kind of this module's catalog states a value for, in name order."""
        return tuple(name for name, p in self.parameters.items() if p.value is None)


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{where} is non-empty text")
    return value


def _parameter(row: Any, where: str) -> Parameter:
    if not isinstance(row, dict) or set(row) != _PARAMETER_KEYS:
        raise ValueError(f"{where} states exactly {sorted(_PARAMETER_KEYS)}")
    minimum, maximum, value = row["minimum"], row["maximum"], row["value"]
    if type(minimum) is not int or type(maximum) is not int or not minimum <= maximum:
        raise ValueError(f"{where} states integer bounds, minimum at most maximum")
    if value is not None and (type(value) is not int or not minimum <= value <= maximum):
        raise ValueError(f"{where} states a value inside its bounds, or none")
    return Parameter(
        name=_text(row["name"], f"{where}.name"),
        minimum=minimum,
        maximum=maximum,
        unit=_text(row["unit"], f"{where}.unit"),
        value=value,
        reason=_text(row["reason"], f"{where}.reason"),
    )


def _module(row: Any) -> MovementModule:
    if not isinstance(row, dict) or set(row) != _ROW_KEYS:
        raise ValueError(f"a movement module row states exactly {sorted(_ROW_KEYS)}")
    name = _text(row["module"], "module")
    where = f"movement module {name}"
    if not name.startswith("exulanica-movement/"):
        raise ValueError(f"{where} is named exulanica-movement/<kind>/v<N>")
    status, refusal = row["status"], row["refusal"]
    if status not in _STATUSES:
        raise ValueError(f"{where} status is one of {_STATUSES}")
    if (status == "built") != (refusal is None):
        raise ValueError(f"{where}: a built module has no refusal and any other names one")
    space, agents, clock, output = row["space"], row["agents"], row["clock"], row["output"]
    if (
        not isinstance(space, dict)
        or set(space) != {"kind", "profiles", "reason"}
        or space["kind"] not in _SPACES
        or not isinstance(space["profiles"], list)
        or not space["profiles"]
        or any(not isinstance(p, str) or not p for p in space["profiles"])
    ):
        raise ValueError(f"{where} space states its kind, one of {_SPACES}, and input profiles")
    kinds = agents.get("kinds") if isinstance(agents, dict) else None
    if (
        not isinstance(agents, dict)
        or set(agents) != {"catalog", "kinds", "reason"}
        or (kinds is not None and (not isinstance(kinds, list) or not kinds))
    ):
        raise ValueError(f"{where} agents names its catalog and its kinds, or null for all")
    if (
        not isinstance(clock, dict)
        or set(clock) != {"kind", "reason", "step_ms"}
        or clock["kind"] not in _CLOCKS
        or type(clock["step_ms"]) is not int
        or clock["step_ms"] < 1
    ):
        raise ValueError(f"{where} clock states its kind, one of {_CLOCKS}, and a step")
    if not isinstance(output, dict) or set(output) != {"profile", "reason"}:
        raise ValueError(f"{where} output states the profile a renderer reads and a reason")
    rows = row["parameters"]
    if not isinstance(rows, list):
        raise ValueError(f"{where} parameters is a list")
    parameters = [_parameter(item, f"{where} parameter {index}") for index, item in enumerate(rows)]
    names = [parameter.name for parameter in parameters]
    if names != sorted(set(names)):
        raise ValueError(f"{where} states each parameter once, in name order")
    return MovementModule(
        module=name,
        status=status,
        refusal=None if refusal is None else _text(refusal, f"{where}.refusal"),
        space_kind=space["kind"],
        space_profiles=tuple(space["profiles"]),
        agents_catalog=_text(agents["catalog"], f"{where}.agents.catalog"),
        agents_kinds=None if kinds is None else tuple(_text(k, f"{where}.kind") for k in kinds),
        clock_kind=clock["kind"],
        step_ms=clock["step_ms"],
        output_profile=_text(output["profile"], f"{where}.output.profile"),
        parameters=MappingProxyType({parameter.name: parameter for parameter in parameters}),
        reason=_text(row["reason"], f"{where}.reason"),
    )


def load_movement_modules(path: Path = MODULES_PATH) -> tuple[MovementModule, ...]:
    """Read and check the table: every module once, in order, each row whole."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or set(document) != {"profile", "modules"}
        or document["profile"] != TABLE_PROFILE
        or not isinstance(document["modules"], list)
        or not document["modules"]
    ):
        raise ValueError(f"{path.name} is not a {TABLE_PROFILE} table")
    modules = tuple(_module(row) for row in document["modules"])
    names = [module.module for module in modules]
    if names != sorted(set(names)):
        raise ValueError("movement modules are listed once each, in order")
    return modules


MODULES: Final = load_movement_modules()
_BY_NAME: Final[Mapping[str, MovementModule]] = MappingProxyType(
    {module.module: module for module in MODULES}
)


def movement_module(name: object) -> MovementModule:
    """The row for ``name``, or a refusal that names what was asked for."""
    module = _BY_NAME.get(name) if isinstance(name, str) else None
    if module is None:
        raise UnknownMovementModule(f"unknown movement module {name!r}")
    return module


def built_module(name: object) -> MovementModule:
    """The row for ``name`` when it is built; an unbuilt row refuses with its own refusal."""
    module = movement_module(name)
    if module.status != "built":
        assert module.refusal is not None
        raise MovementModuleNotConnected(module.module, module.refusal)
    return module
