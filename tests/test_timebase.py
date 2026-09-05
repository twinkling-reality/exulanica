"""The canonical timebase, the rational anchor, and the degenerate photograph interval."""

from __future__ import annotations

import pytest
from exulanica.errors import InvalidAddressError
from exulanica.evidence import (
    IMAGE_TIME_BASE,
    NS_PER_SECOND,
    PHOTOGRAPH_INTERVAL,
    TimeBase,
    TimeInterval,
    ns_to_seconds,
    seconds_to_ns,
)


def test_photograph_interval_is_the_smallest_non_empty_half_open_interval():
    assert TimeInterval(0, 1) == PHOTOGRAPH_INTERVAL
    assert PHOTOGRAPH_INTERVAL.duration_ns == 1


def test_an_empty_interval_is_refused():
    """[0, 0) contains nothing and overlaps nothing.

    If images were allowed an empty interval, the tombstone interval guard would test overlap
    against it, find none, and silently fail open. That is the specific bug this refusal
    prevents, so it is asserted rather than assumed.
    """
    with pytest.raises(InvalidAddressError):
        TimeInterval(0, 0)
    with pytest.raises(InvalidAddressError):
        TimeInterval(500, 100)


def test_two_photographs_overlap_the_way_two_video_moments_do():
    """Co-presence in one photograph must be the same query as co-presence in one video moment."""
    face_a = PHOTOGRAPH_INTERVAL
    face_b = PHOTOGRAPH_INTERVAL
    assert face_a.overlaps(face_b)
    assert TimeInterval(0, 4_000_000_000).overlaps(TimeInterval(3_000_000_000, 9_000_000_000))
    assert not TimeInterval(0, 1).overlaps(TimeInterval(1, 2))  # half-open, so they abut


def test_image_timebase_is_the_canonical_axis():
    assert TimeBase(1, NS_PER_SECOND) == IMAGE_TIME_BASE
    assert IMAGE_TIME_BASE.ticks_from_ns(0) == 0
    assert IMAGE_TIME_BASE.ticks_from_ns(1) == 1
    assert IMAGE_TIME_BASE.ns_from_ticks(1) == 1


def test_the_conversion_formulas_produce_exactly_the_documented_values():
    """Pins both directions at 48 kHz and at 1/15360 video ticks.

    A 1/48000 s tick is 20833.333... ns, which nanoseconds cannot hold exactly. That is the
    whole reason the rational anchor is stored rather than discarded once t_ns is computed.
    """
    audio = TimeBase(1, 48_000)
    assert audio.ns_from_ticks(0) == 0
    assert audio.ns_from_ticks(1) == 20_834  # ceil of 20833.333..., so tick 1 survives the trip
    assert audio.ns_from_ticks(3) == 62_500  # exact, so ceiling changes nothing
    assert audio.ns_from_ticks(48_000) == NS_PER_SECOND
    assert audio.ticks_from_ns(NS_PER_SECOND) == 48_000
    assert audio.ticks_from_ns(20_832) == 0  # floor: still inside tick 0
    assert audio.ticks_from_ns(20_834) == 1

    video = TimeBase(1, 15_360)
    assert video.ns_from_ticks(15_360) == NS_PER_SECOND
    assert video.ticks_from_ns(NS_PER_SECOND) == 15_360


@pytest.mark.parametrize(
    ("num", "den", "what"),
    [
        (1, 48_000, "48 kHz audio"),
        (1, 44_100, "44.1 kHz audio"),
        (1, 90_000, "MPEG transport"),
        (1, 15_360, "a common video timebase"),
        (1001, 30_000, "NTSC 29.97, where num is not 1"),
        (1, NS_PER_SECOND, "the canonical axis itself"),
    ],
)
def test_tick_to_ns_to_tick_is_the_identity(num, den, what):
    """The defect this used to pin is fixed, and this is what replaced the pin.

    ``ns_from_ticks`` rounded to nearest while ``ticks_from_ns`` floors, so any tick whose
    nanosecond value rounded *down* landed back on the previous tick: audio tick 1 rendered as
    20833 ns and floored straight back to tick 0. A citation stored in nanoseconds and converted
    back to a tick for a seek opened one sample early.

    Ceiling composes with floor exactly. ADR-0015 records why the correction cost nothing when it
    was taken and why it would not have been free later. This test is the guard on the other
    direction now: a change back to nearest, or to any rule that is not an inverse of the floor,
    fails here rather than one sample early inside somebody's playback.

    Negative ticks are included because they are real: ``start_pts`` later than track zero puts a
    span before it, and edit lists produce that routinely.
    """
    base = TimeBase(num, den)
    for ticks in (*range(-1_000, 1_000), 2**31, -(2**31), 10**9, -(10**9)):
        assert base.ticks_from_ns(base.ns_from_ticks(ticks)) == ticks, (ticks, what)


def test_a_tick_that_would_overflow_the_axis_is_refused_at_the_conversion():
    """int64 nanoseconds is 292 years. A PTS past that is corrupt, and says so here.

    Leaving it to the ``bigint`` column would report the failure three layers away from the
    timebase that explains it.
    """
    ntsc = TimeBase(1001, 30_000)
    with pytest.raises(InvalidAddressError, match="does not fit in int64"):
        ntsc.ns_from_ticks(10**12)
    assert ntsc.ticks_from_ns(ntsc.ns_from_ticks(10**11)) == 10**11


def test_a_timebase_finer_than_a_nanosecond_is_refused():
    """Two ticks sharing one t_ns cannot both round trip, so the axis refuses to hold them.

    No container declares such a timebase. Refusing costs nothing and removes the one family of
    inputs for which the identity above cannot hold.
    """
    with pytest.raises(InvalidAddressError, match="finer than one nanosecond"):
        TimeBase(1, NS_PER_SECOND + 1)
    # Exactly one nanosecond per tick is the finest representable, and it is the image timebase.
    assert TimeBase(1, NS_PER_SECOND) == IMAGE_TIME_BASE


def test_the_correction_moved_no_photograph_boundary():
    """The photograph corpus is why the correction was free: its timebase converts exactly.

    Every span that exists is a photograph carrying [0, 1) directly. On the canonical axis
    ceiling and nearest agree on every value, so no stored digest could have moved.
    """
    for ticks in (0, 1, 2, 1_000_000, -1, -1_000_000):
        assert IMAGE_TIME_BASE.ns_from_ticks(ticks) == ticks


def test_tick_conversion_floors_toward_negative_infinity_for_negative_times():
    """Negative t_ns is real: it happens whenever start_pts is later than track zero."""
    base = TimeBase(1, 48_000)
    assert base.ticks_from_ns(-1) == -1  # floor, not truncation toward zero
    assert base.ticks_from_ns(-20_834) == -2


def test_a_non_positive_timebase_is_refused():
    with pytest.raises(InvalidAddressError):
        TimeBase(0, 1000)
    with pytest.raises(InvalidAddressError):
        TimeBase(1, -1000)


@pytest.mark.parametrize(
    "t_ns",
    [0, 1, 999_999_999, 1_000_000_000, 12_500_000_000, -1, -12_500_000_001, 2**62],
)
def test_seconds_rendering_is_lossless(t_ns):
    assert seconds_to_ns(ns_to_seconds(t_ns)) == t_ns


def test_seconds_rendering_matches_the_documented_permalink_form():
    assert ns_to_seconds(12_500_000_000) == "12.5"
    assert ns_to_seconds(18_250_000_000) == "18.25"
    assert ns_to_seconds(0) == "0"
    assert ns_to_seconds(1) == "0.000000001"


def test_sub_nanosecond_seconds_are_refused_rather_than_rounded():
    """Silently rounding would move a citation boundary and change its digest."""
    with pytest.raises(InvalidAddressError):
        seconds_to_ns("1.0000000005")
