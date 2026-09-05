"""The canonical timebase: signed int64 nanoseconds plus a stored rational anchor.

Two axes, deliberately kept apart:

*   ``t_ns`` is the canonical axis. Signed int64 nanoseconds since track zero. Every span,
    query and UI element uses it, because it is comparable across track kinds and indexes as a
    plain ``int8range``.
*   ``TimeBase`` is the exact anchor, the ``time_base_num`` / ``time_base_den`` rational
    observed at ingest, stored verbatim on the track row. Nanoseconds cannot exactly represent
    a 1/48000 s audio tick (20833.333... ns), which is why the rational is kept rather than
    discarded once ``t_ns`` is computed.

The two conversion formulas are contract, and changing either moves ``t_start_ns`` and
``t_end_ns`` for any span derived through them, which changes the span digest and therefore every
citation token and permalink issued against it.

    ticks(t_ns) = floor( (t_ns * den) / (num * 1_000_000_000) )
    t_ns(ticks) = ceil( ticks * num * 1_000_000_000 / den )

**The second formula was corrected on 2026-09-04, inside its decision window (ADR-0015).** It
used to round to nearest, under a rule the committed contract named and never defined. Rounding
to nearest reads as the more accurate choice and is the wrong one, because it does not compose
with the flooring in the other direction: at 48 kHz one tick is 20833.333... ns, tick 1 rendered
as 20833 ns, and 20833 ns floored straight back to tick 0. A citation stored in nanoseconds and
converted back to a tick for a seek opened one sample early.

Ceiling fixes it exactly, not approximately. ``ticks_from_ns`` answers "which tick contains this
nanosecond", so only a boundary at or after the true instant lands back on the tick it came from,
and ``ticks(t_ns(k)) == k`` for every ``k`` on every timebase whose tick is at least one
nanosecond. It holds for negative ticks too, which is why the rule is toward positive infinity
rather than away from zero.

The correction was free and provably so: at the time it was taken, ``ns_from_ticks`` and
``ticks_from_ns`` had **no callers outside this package's tests**, no ``video`` or ``audio``
``media_track`` row had ever been written, and every existing span was a photograph carrying
``[0, 1)`` directly rather than through a conversion. Not one stored digest moved, so
``span_format_version`` stays at 1: writing a v2 alongside v1 would have created two formats
agreeing on every span that exists.

``round_half_down`` remains the rule for quantising a measured value, and its tie direction is
**ratified as ties toward zero**, the standard reading of the name that ``decimal.ROUND_HALF_DOWN``
and Java's ``RoundingMode.HALF_DOWN`` take. It no longer takes part in the timebase.

A photograph is the degenerate case and is not special-cased anywhere: it is a single-sample
track whose timebase is the canonical axis itself (1/1_000_000_000), whose ``start_pts`` is 0,
and whose interval is ``[0, 1)`` nanoseconds, the smallest non-empty half-open interval. The
interval is a structural placeholder and carries no semantics about the photograph. It exists
so that the interval-overlap paths, the tombstone interval guard, and the digest tuple shape
are exercised by the photograph corpus rather than left untested until video arrives.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from exulanica.canonical import ceil_div
from exulanica.errors import InvalidAddressError

__all__ = [
    "IMAGE_TIME_BASE",
    "NS_PER_SECOND",
    "PHOTOGRAPH_INTERVAL",
    "TimeBase",
    "TimeInterval",
    "ns_to_seconds",
    "seconds_to_ns",
]

NS_PER_SECOND: Final = 1_000_000_000

_INT64_MIN: Final = -(2**63)
_INT64_MAX: Final = 2**63 - 1


def _check_int64(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidAddressError(f"{label} must be an int, got {type(value).__name__}")
    if not _INT64_MIN <= value <= _INT64_MAX:
        raise InvalidAddressError(f"{label} does not fit in int64: {value}")
    return value


@dataclass(frozen=True, slots=True)
class TimeBase:
    """A track's exact rational timebase, stored as observed rather than normalised.

    ``Fraction`` is deliberately not used: it reduces 2/30 to 1/15, and the point of this type
    is to round-trip what the container actually declared, so that a re-probe of the same bytes
    can be compared against what was stored.
    """

    num: int
    den: int

    def __post_init__(self) -> None:
        if not isinstance(self.num, int) or not isinstance(self.den, int):
            raise InvalidAddressError("time base components must be ints")
        if self.num <= 0 or self.den <= 0:
            raise InvalidAddressError(f"time base must be positive, got {self.num}/{self.den}")
        if self.den > self.num * NS_PER_SECOND:
            # A tick finer than one nanosecond cannot be placed on the canonical axis at all:
            # two ticks would share a t_ns and the round trip could not be exact for both. No
            # container declares one. Refusing beats storing boundaries that cannot round trip.
            raise InvalidAddressError(
                f"time base {self.num}/{self.den} has a tick finer than one nanosecond, which "
                "the canonical axis cannot represent. The finest representable timebase is "
                f"1/{NS_PER_SECOND}."
            )

    def ticks_from_ns(self, t_ns: int) -> int:
        """Contract: floor((t_ns * den) / (num * 1e9)).

        Floor, because the question is "which tick contains this nanosecond". Rounding to
        nearest here would answer a different question and would break ``frame_at``.
        """
        _check_int64(t_ns, "t_ns")
        return (t_ns * self.den) // (self.num * NS_PER_SECOND)

    def ns_from_ticks(self, ticks: int) -> int:
        """Contract: ceil(ticks * num * 1e9 / den).

        Ceiling is what makes this the exact inverse of ``ticks_from_ns``. See the module
        docstring and ADR-0015 for why nearest was wrong and why correcting it cost nothing.
        """
        if not isinstance(ticks, int) or isinstance(ticks, bool):
            raise InvalidAddressError("ticks must be an int")
        # Checked here rather than left to the bigint column. A tick far enough out to overflow
        # the axis is a corrupt or misread PTS, and the useful place to say so is at the
        # conversion, where the timebase is still in hand to put in the message.
        return _check_int64(
            ceil_div(ticks * self.num * NS_PER_SECOND, self.den),
            f"tick {ticks} on timebase {self}",
        )

    def __str__(self) -> str:
        return f"{self.num}/{self.den}"


#: The timebase of a still photograph: the canonical axis is its own timebase.
IMAGE_TIME_BASE: Final = TimeBase(1, NS_PER_SECOND)


@dataclass(frozen=True, slots=True, order=True)
class TimeInterval:
    """A half-open interval ``[start_ns, end_ns)`` on the canonical nanosecond axis.

    Half-open matches Media Fragments URI 1.0: the begin time is part of the interval and the
    end time is the first point that is not. Empty intervals are refused at construction,
    because an empty range is contained by nothing and overlaps nothing, so it would make the
    tombstone interval guard silently fail open.

    Ordering is by ``(start_ns, end_ns)``, which gives a citation list one deterministic
    playback order.
    """

    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        _check_int64(self.start_ns, "start_ns")
        _check_int64(self.end_ns, "end_ns")
        if self.end_ns <= self.start_ns:
            raise InvalidAddressError(
                f"interval must be non-empty and half-open: [{self.start_ns}, {self.end_ns}) "
                "has end <= start. A photograph uses [0, 1), never [0, 0)."
            )

    @property
    def duration_ns(self) -> int:
        return self.end_ns - self.start_ns

    def contains(self, t_ns: int) -> bool:
        return self.start_ns <= t_ns < self.end_ns

    def overlaps(self, other: TimeInterval) -> bool:
        """True when the two half-open intervals share at least one nanosecond."""
        return self.start_ns < other.end_ns and other.start_ns < self.end_ns

    @classmethod
    def from_seconds(cls, start: str, end: str) -> TimeInterval:
        """Parse two decimal-second strings exactly, without going through float."""
        return cls(seconds_to_ns(start), seconds_to_ns(end))

    def __str__(self) -> str:
        return f"[{self.start_ns}, {self.end_ns})"


#: The degenerate interval every still photograph carries.
PHOTOGRAPH_INTERVAL: Final = TimeInterval(0, 1)


def seconds_to_ns(text: str) -> int:
    """Parse a decimal-seconds string to exact integer nanoseconds.

    Deliberately not ``float(text) * 1e9``: binary floating point cannot represent most
    decimal fractions, so a round trip through float would move citation boundaries by a
    nanosecond or two and change the span digest.
    """
    candidate = text.strip()
    if not candidate:
        raise InvalidAddressError("empty seconds value")
    negative = candidate.startswith("-")
    if negative or candidate.startswith("+"):
        candidate = candidate[1:]
    whole, _, frac = candidate.partition(".")
    if not whole.isdigit() or (frac and not frac.isdigit()):
        raise InvalidAddressError(f"not a decimal seconds value: {text!r}")
    if len(frac) > 9:
        raise InvalidAddressError(
            f"seconds value {text!r} has sub-nanosecond precision, which the canonical axis "
            "cannot represent"
        )
    value = int(whole) * NS_PER_SECOND + int(frac.ljust(9, "0") or "0")
    return -value if negative else value


def ns_to_seconds(t_ns: int) -> str:
    """Render exact integer nanoseconds as a decimal-seconds string.

    Trailing zeros in the fraction are trimmed and the point is dropped for whole seconds, so
    ``12500000000`` renders as ``12.5`` and ``0`` as ``0``. The rendering is injective over
    int64 nanoseconds, so ``seconds_to_ns(ns_to_seconds(x)) == x`` for every representable x.
    """
    _check_int64(t_ns, "t_ns")
    sign = "-" if t_ns < 0 else ""
    magnitude = abs(t_ns)
    whole, frac = divmod(magnitude, NS_PER_SECOND)
    if frac == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{frac:09d}".rstrip("0")
