"""The step each built movement module moves its agents by, keyed by the module's identity.

The registry (:mod:`exulanica.movement.registry`) states which modules exist and which are built;
this table is the code each built one runs, and a test holds the two to the same set of names. A
caller asks :func:`step_of` for a module's step, never imports a step by hand: an unknown module
is refused by name, and one the table states but does not build is refused with its own refusal.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Final

from exulanica.movement import flight, walking
from exulanica.movement.registry import FLIGHT, WALKING, built_module

__all__ = ["STEPS", "step_of"]

#: One entry per built module. Each module's step has its own signature, stated where it is
#: defined: walking's traverses a route, flight's computes a window of steps.
STEPS: Final[Mapping[str, Callable[..., Any]]] = MappingProxyType(
    {WALKING: walking.traverse, FLIGHT: flight.flight_window}
)


def step_of(name: object) -> Callable[..., Any]:
    """The step of the built module ``name``; an unknown or unbuilt module is refused by name."""
    return STEPS[built_module(name).module]
