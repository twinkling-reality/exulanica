"""The one draw every generated value comes from.

    _number(seed, domain, ordinal)
        = int.from_bytes(sha256(f"{seed}:{domain}:{ordinal}".encode()).digest()[:8], "big")

**Domain-namespaced, which is the rule that matters.** A draw depends on its seed, its domain
and its ordinal, and on nothing else: there is no shared stream and no global counter. Adding a
stage, or adding draws to an existing stage under a new domain, therefore cannot move a single
value any earlier stage produced. A :class:`DomainCursor` keeps its own ordinal for exactly this
reason; two cursors never share one.

**Integers only.** No float enters or leaves this module. A bounded draw uses multiply-shift,
``minimum + (n * span >> 64)``, which is exact integer arithmetic. Each outcome is reached by
either ``floor(2**64 / span)`` or ``ceil(2**64 / span)`` of the 64-bit inputs, so the largest
relative bias is below ``span / 2**64``. Spans are capped at ``2**32`` to keep that under one
part in four billion.

**Domain grammar.** Lowercase ASCII words joined by dots, for example ``streets.hierarchy``. A
colon is refused, so the preimage ``seed:domain:ordinal`` splits one way only. An ordinal is a
non-negative ``int`` and exactly an ``int``: ``True`` formats as ``"True"``, and any other
``int`` subclass is free to format itself some other way.
"""

from __future__ import annotations

import hashlib
import re
from typing import Final

from exulanica.grammar.errors import InvalidDomainError
from exulanica.grammar.seed import require_seed

__all__ = [
    "DRAW_BITS",
    "MAX_SPAN",
    "DomainCursor",
    "_number",
    "draw_integer",
    "require_domain",
    "require_ordinal",
]

DRAW_BITS: Final = 64
MAX_SPAN: Final = 1 << 32

_DOMAIN: Final = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*")


def require_domain(domain: object) -> str:
    """Return ``domain`` if it is a well formed draw namespace, or raise."""
    if type(domain) is not str or _DOMAIN.fullmatch(domain) is None:
        raise InvalidDomainError(
            f"a draw domain is lowercase ASCII words joined by dots, got {domain!r}"
        )
    return domain


def require_ordinal(ordinal: object) -> int:
    """Return ``ordinal`` if it is exactly a non-negative ``int``, or raise."""
    if type(ordinal) is not int or ordinal < 0:
        raise InvalidDomainError(f"a draw ordinal is a non-negative int, got {ordinal!r}")
    return ordinal


def _number(seed: str, domain: str, ordinal: int) -> int:
    """The draw, exactly as the architecture specifies it. A 64-bit unsigned integer."""
    require_seed(seed)
    require_domain(domain)
    require_ordinal(ordinal)
    digest = hashlib.sha256(f"{seed}:{domain}:{ordinal}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def draw_integer(seed: str, domain: str, ordinal: int, minimum: int, maximum: int) -> int:
    """An integer in ``[minimum, maximum]``, both inclusive, from one draw."""
    span = _span(minimum, maximum)
    return minimum + ((_number(seed, domain, ordinal) * span) >> DRAW_BITS)


def _span(minimum: object, maximum: object) -> int:
    if type(minimum) is not int or type(maximum) is not int:
        raise InvalidDomainError("draw bounds are ints")
    span = maximum - minimum + 1
    if span < 1:
        raise InvalidDomainError(f"empty draw range [{minimum}, {maximum}]")
    if span > MAX_SPAN:
        raise InvalidDomainError(f"draw range [{minimum}, {maximum}] is wider than 2**32")
    return span


class DomainCursor:
    """Successive draws in one domain. Owns its ordinal, so no other domain can move it."""

    __slots__ = ("_domain", "_ordinal", "_seed")

    def __init__(self, seed: str, domain: str) -> None:
        self._seed = require_seed(seed)
        self._domain = require_domain(domain)
        self._ordinal = 0

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def ordinal(self) -> int:
        """The ordinal the next draw will use."""
        return self._ordinal

    def number(self) -> int:
        value = _number(self._seed, self._domain, self._ordinal)
        self._ordinal += 1
        return value

    def integer(self, minimum: int, maximum: int) -> int:
        span = _span(minimum, maximum)
        return minimum + ((self.number() * span) >> DRAW_BITS)
