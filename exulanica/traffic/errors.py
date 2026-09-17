"""Errors raised by the traffic simulation.

A refused network, a refused catalog and a refused input are different mistakes made by
different parties, so each has its own class. None of them is ever absorbed by a default.
"""

from __future__ import annotations

from exulanica.errors import ExulanicaError

__all__ = [
    "InvalidTrafficInputError",
    "InvalidTrafficStateError",
    "TrafficCatalogError",
    "TrafficError",
    "UnsupportedNetworkError",
]


class TrafficError(ExulanicaError):
    """Base class for every error raised by ``exulanica.traffic``."""


class TrafficCatalogError(TrafficError, ValueError):
    """A traffic catalog breaks its envelope, its entry schema or its source rule."""


class UnsupportedNetworkError(TrafficError, ValueError):
    """The road records are invalid, or valid and outside what this profile can simulate.

    The message always states which. A network is never approximated to make it fit.
    """


class InvalidTrafficInputError(TrafficError, ValueError):
    """A trip request or a crossing occupancy is malformed, unknown or out of order."""


class InvalidTrafficStateError(TrafficError, ValueError):
    """A state document is not one this profile produced, or its digests do not match."""
