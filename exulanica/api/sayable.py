"""A refusal's words said back only as JSON and UTF-8 can carry them.

A client's own value can reach a refusal: a key it named, a value it sent. JSON parses a lone
surrogate escape, and Python's reader a NaN or an infinity, and neither can be written back (a
response's JSON is strict and its text UTF-8), so a refusal carrying one would answer 500.
:func:`sayable` writes a lone surrogate as its escape and a number JSON cannot say as its words, and
leaves everything else as it was.
"""

from __future__ import annotations

import math

__all__ = ["sayable"]


def sayable(value: object) -> object:
    """``value`` with every string UTF-8 can carry and every number JSON can say, recursively."""
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return value.encode("utf-8", "backslashreplace").decode("utf-8")
        return value
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, dict):
        return {str(sayable(key)): sayable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [sayable(item) for item in value]
    return value
