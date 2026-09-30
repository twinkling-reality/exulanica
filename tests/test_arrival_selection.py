"""The v4 opening remains a drawable region of its own saved world."""

from __future__ import annotations

import datetime as dt

from exulanica.world.arrival_selection import (
    OwnedSource,
    fallback_arrival_pose,
    select_owned_opening_region,
)


def _source(region: str, capture: str, hour: int, *, available: bool = True) -> OwnedSource:
    return OwnedSource(
        region, (capture,), dt.datetime(2026, 9, 30, hour, tzinfo=dt.UTC), available
    )


def test_owned_region_precedes_earlier_unrelated_workspace_sources_and_display_limit():
    unrelated = [f"elsewhere-{index}" for index in range(6)]
    graph = [*unrelated, "owned-early", "owned-late"]
    sources = [_source("world:early", "owned-early", 11),
               _source("world:late", "owned-late", 12)]
    assert select_owned_opening_region(
        sources,
        {"world:early", "world:late"},
        graph,
        ["world:late", "world:late", "world:early"],
    ) == "world:late"
    assert select_owned_opening_region(
        sources,
        {"world:early", "world:late"},
        graph,
        [],
    ) == "world:early"


def test_no_authorized_drawable_owned_source_has_no_arrival():
    sources = [_source("world:withdrawn", "capture-a", 9, available=False),
               _source("world:unseen", "capture-b", 10)]
    assert select_owned_opening_region(
        sources,
        {"world:withdrawn", "world:unseen"},
        {"capture-a"},
        ["world:unseen"],
    ) is None


def test_capture_held_in_two_regions_cannot_choose_either():
    sources = [_source("world:a", "same-capture", 9),
               _source("world:b", "same-capture", 10)]
    assert select_owned_opening_region(
        sources,
        {"world:a", "world:b"},
        {"same-capture"},
        ["world:a"],
    ) is None


def test_photograph_fallback_uses_the_renderer_radius_and_integer_units():
    assert fallback_arrival_pose(0) == ((0, 1600, 3600), (0, -84898, -996390))
    distant, forward = fallback_arrival_pose(200)
    assert distant == (0, 1600, 4400)
    assert forward == (0, -84898, -996390)
