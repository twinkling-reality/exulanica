"""The step each built movement module moves its agents by, keyed by the module's identity.

The registry (:mod:`exulanica.movement.registry`) states which modules exist and which are built;
this table is the code each built one runs, and a test holds the two to the same set of names. A
caller asks :func:`step_of` for a module's step, never imports a step by hand: an unknown module
is refused by name, and one the table states but does not build is refused with its own refusal.

**A hosted module.** A built module whose step lives in a package this one may not import runs in
a host above both: roads, whose step is the traffic simulation's, runs in
:mod:`exulanica.world.traffic_episodes`. :data:`HOSTED` names that host, a test resolves it, and
:func:`step_of` refuses such a module by name, ``movement_step_hosted``, rather than guessing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Final

from exulanica.movement import flight, walking
from exulanica.movement.registry import FLIGHT, ROADS, WALKING, MovementError, built_module

__all__ = ["HOSTED", "STEPS", "MovementStepHosted", "step_of"]

#: One entry per built module this package runs. Each module's step has its own signature, stated
#: where it is defined: walking's traverses a route, flight's computes a window of steps.
STEPS: Final[Mapping[str, Callable[..., Any]]] = MappingProxyType(
    {WALKING: walking.traverse, FLIGHT: flight.flight_window}
)
#: Built modules whose step runs in a host above this package, by the module that runs it.
HOSTED: Final[Mapping[str, str]] = MappingProxyType({ROADS: "exulanica.world.traffic_episodes"})


class MovementStepHosted(MovementError):
    """A built module whose step runs in a host above this package, named with the host."""

    def __init__(self, module: str, host: str) -> None:
        super().__init__(f"movement module {module!r} runs in its host, {host}")
        self.module = module
        self.host = host
        self.code = "movement_step_hosted"

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self.module, self.host))


def step_of(name: object) -> Callable[..., Any]:
    """The step of the built module ``name``; an unknown, unbuilt or hosted module is refused by
    name."""
    module = built_module(name).module
    if module in HOSTED:
        raise MovementStepHosted(module, HOSTED[module])
    return STEPS[module]
