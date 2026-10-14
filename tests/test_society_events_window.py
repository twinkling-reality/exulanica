"""A society's events read by a window of minutes and by kind, oldest first, as a page draws them.

The events read pages back from the newest. A page that draws a minute (a late joiner, a scrub, a
replay of a stretch) needs that minute's events in the order they happened, and a page that shows
speech needs only the lines. Against PostgreSQL, through the route a page reads, over a starter
world's society stepped through several minutes:

*   a window answers exactly the whole read's events of those minutes, oldest first (minute, then
    order, then id), and a kinds filter exactly those of the kinds named, with or without a window;
*   a window read page by page with ``after`` covers the window once, in order;
*   a window that ends before it begins, ``before`` with a window, ``after`` without one, a cursor
    outside the window and a malformed kind are refused by name (``invalid_events_window``);
*   a read naming none of them answers as it always did.
"""

from __future__ import annotations

from typing import Any

import pytest

from test_society_made_world import made as imported_made  # noqa: F401
from test_world_capabilities_api import _place, _starter, _version_path

pytestmark = pytest.mark.postgres


@pytest.fixture(name="api")
def _api(request):
    return request.getfixturevalue("imported_made")


def _key(event: dict[str, Any]) -> tuple[int, float, str]:
    order = event["document"].get("order")
    return (event["tick"], float("inf") if order is None else order, event["event_id"])


def _stepped(api, minutes: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    entry = _starter(api)
    assert _place(api, entry, "region:starter").status_code == 201
    created = api.post(
        _version_path(entry, "/society"),
        {"region_id": "region:starter", "profile": "exulanica-society/v2"},
    )
    assert created.status_code == 200, created.text
    snapshot = created.json()
    for _ in range(minutes):
        stepped = api.post(
            _version_path(entry, "/society/steps"),
            {"base_tick": snapshot["current_tick"], "base_state_sha256": snapshot["state_sha256"]},
        )
        assert stepped.status_code == 200, stepped.text
        snapshot = stepped.json()
    whole = api.get(_version_path(entry, "/society/events"))
    assert whole.status_code == 200, whole.text
    assert whole.json()["next"] is None
    return entry, whole.json()["events"]


def _read(api, entry: dict[str, Any], query: str) -> dict[str, Any]:
    answer = api.get(_version_path(entry, f"/society/events?{query}"))
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_a_window_and_kinds_answer_exactly_those_events_oldest_first(api):
    entry, everything = _stepped(api, 6)
    ticks = sorted({event["tick"] for event in everything})
    kinds = sorted({event["event_kind"] for event in everything})
    assert len(ticks) >= 4 and len(kinds) >= 2, (ticks, kinds)
    low, high = ticks[1], ticks[-2]
    oldest_first = sorted(everything, key=_key)
    window = _read(api, entry, f"from_tick={low}&to_tick={high}")
    assert window["events"] == [e for e in oldest_first if low <= e["tick"] <= high]
    assert window["next"] is None
    # An open end is the first or the latest minute.
    assert _read(api, entry, f"from_tick={high}")["events"] == [
        e for e in oldest_first if e["tick"] >= high
    ]
    assert _read(api, entry, f"to_tick={low}")["events"] == [
        e for e in oldest_first if e["tick"] <= low
    ]
    # A kinds filter, with a window oldest first, and without one newest first as always.
    kind = kinds[0]
    assert _read(api, entry, f"kinds={kind}&from_tick={low}&to_tick={high}")["events"] == [
        e for e in oldest_first if low <= e["tick"] <= high and e["event_kind"] == kind
    ]
    assert _read(api, entry, f"kinds={kind}")["events"] == [
        e for e in everything if e["event_kind"] == kind
    ]
    both = f"kinds={kinds[0]}&kinds={kinds[1]}"
    assert _read(api, entry, both)["events"] == [
        e for e in everything if e["event_kind"] in kinds[:2]
    ]
    # The positive control: a read naming none of them answers as it always did.
    assert _read(api, entry, "")["events"] == everything


def test_a_window_reads_on_page_by_page_and_covers_it_once(api):
    entry, everything = _stepped(api, 6)
    ticks = sorted({event["tick"] for event in everything})
    low, high = ticks[0], ticks[-1]
    expected = sorted(everything, key=_key)
    pages: list[dict[str, Any]] = []
    cursor = None
    while True:
        query = f"from_tick={low}&to_tick={high}&limit=3" + (f"&after={cursor}" if cursor else "")
        page = _read(api, entry, query)
        pages.extend(page["events"])
        cursor = page["next"]
        if cursor is None:
            break
        assert len(page["events"]) == 3
    assert pages == expected


def test_a_window_that_cannot_be_read_is_refused_by_name(api):
    entry, everything = _stepped(api, 3)
    ticks = sorted({event["tick"] for event in everything})
    newest = everything[0]
    order = newest["document"].get("order")
    cursor = f"{newest['tick']}:{'' if order is None else order}:{newest['event_id']}"
    assert newest["tick"] == ticks[-1] >= 1
    refused = [
        # A window that ends before it begins.
        "from_tick=2&to_tick=1",
        # A window is read on with after, never before; after continues only a window.
        f"from_tick=0&before={cursor}",
        f"after={cursor}",
        # A cursor naming an event outside the window.
        f"from_tick=0&to_tick={ticks[-1] - 1}&after={cursor}",
        # A kind that is not an event kind's shape.
        "kinds=Not-A-Kind",
    ]
    for query in refused:
        answer = api.get(_version_path(entry, f"/society/events?{query}"))
        assert answer.status_code == 422, (query, answer.text)
        assert answer.json()["code"] == "invalid_events_window", (query, answer.json())
