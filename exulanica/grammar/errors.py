"""Errors raised by the generator system.

Separate classes rather than bare ``ValueError`` because the difference between them is the
difference between a caller's mistake and a data file's: an invalid seed is refused at the door,
an unresolved catalog reference is a schema error in reviewed data, and neither is ever absorbed
by a default.

A float in a record is not one of these. It raises ``exulanica.errors.CanonicalisationError``
from ``exulanica.canonical``, deliberately, so the refusal a digest relies on is the one that
fires rather than a second check that could drift from it.
"""

from __future__ import annotations

from exulanica.errors import ExulanicaError

__all__ = [
    "CatalogError",
    "GrammarError",
    "InvalidDomainError",
    "InvalidParameterError",
    "InvalidRecordError",
    "InvalidSeedError",
    "UnregisteredGrammarError",
    "UnresolvedReferenceError",
]


class GrammarError(ExulanicaError):
    """Base class for every error raised by ``exulanica.grammar``."""


class InvalidSeedError(GrammarError, ValueError):
    """A seed is not 64 lowercase hexadecimal characters. Never repaired, never defaulted."""


class InvalidDomainError(GrammarError, ValueError):
    """A draw domain or ordinal is not well formed, so its draws would not be namespaced."""


class InvalidParameterError(GrammarError, ValueError):
    """A parameter is unknown, out of its declared range, bound twice, or required and unset."""


class InvalidRecordError(GrammarError, ValueError):
    """A record, a stage emission or a receipt breaks its declared shape."""


class UnregisteredGrammarError(GrammarError, KeyError):
    """No grammar is registered under this id and version."""


class CatalogError(GrammarError, ValueError):
    """A catalog file breaks its envelope or its entry schema."""


class UnresolvedReferenceError(CatalogError):
    """A catalog entry names something that does not exist. A schema error, not a default."""
