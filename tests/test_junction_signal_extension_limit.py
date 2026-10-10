"""A green that already holds every extension its plan allows offers no further choice point.

A model's ``keep`` extends a green by one second, at most ``green_extension_seconds_maximum``
times (:mod:`exulanica.traffic.signal_actuation`). Once the green holds them all, amber follows
whatever is answered, and :class:`~exulanica.traffic.signal_actuation.SignalTimeline` accepts no
choice at that second. The observation that makes a second a choice point says the same, so a
model that keeps every green as long as it may is never asked a question no answer can be
recorded for, and a world's traffic keeps being prepared.
"""

from __future__ import annotations

import hashlib
from functools import cache

import pytest
from exulanica.canonical import canonical_json
from exulanica.traffic.signal_actuation import SignalTimeline, signal_actuation, signal_observation
from exulanica.world.generated_worlds import compose_specified_world
from exulanica.world.traffic_episodes import (
    TrafficInput,
    compute_signal_catalog,
    compute_signal_probe,
    traffic_input,
    wire,
)

import traffic_corridor_support as corridor
from living_town_support import before_floor_area

#: The corridor signal the continuation tests read.
CORRIDOR_SIGNAL = "4c2a6323-4ae3-5581-9d67-d681421f0f12"
#: The town here is made as towns were made before their homes followed floor area: a town's
#: traffic is seeded by its receipt, which pins the routine it was made under, and the histories
#: below were read for that town.
pytestmark = pytest.mark.usefixtures(before_floor_area.__name__)

#: A small town whose first signal meets a run of twelve keeps with a vehicle still near it.
TOWN = "small_town"
TOWN_WORLD = "world:generated:v7-signal-small_town-0"
#: The first seconds of the episode, which hold that run: through second 314.
SECONDS = 360
MOST = signal_actuation().green_extension_seconds_maximum


def _minimum_green_seconds() -> int:
    """The plan's green before its first choice point: its first two intervals, walk and
    clearance."""
    plan = corridor.prepared().catalogs.plan(signal_actuation().plan)
    return (plan.intervals[0].duration_ms + plan.intervals[1].duration_ms) // 1000


def _corridor_timeline(choices: dict[int, str]) -> SignalTimeline:
    ready = corridor.prepared()
    signal = next(
        junction.signal
        for junction in ready.network.junctions.values()
        if junction.signal is not None and junction.signal.identity == CORRIDOR_SIGNAL
    )
    return SignalTimeline(
        ready.catalogs.plan(signal.plan),
        signal.offset_s,
        0,
        1260,
        choices,
        signal_actuation(),
    )


def _offered(second: int, timeline: SignalTimeline) -> bool:
    observation = signal_observation(
        {"second": second, "vehicles": []}, corridor.prepared().network, timeline, CORRIDOR_SIGNAL
    )
    return observation is not None


def test_a_green_holding_its_most_extensions_offers_no_further_choice_point():
    first = next(second for second in range(1, 120) if _offered(second, _corridor_timeline({})))
    keeps: dict[int, str] = {}
    for extension in range(MOST):
        # While the green has room for one more second, each second of the run is a choice.
        assert _offered(first + extension, _corridor_timeline(keeps))
        keeps[first + extension] = "keep"
    assert not _offered(first + MOST, _corridor_timeline(keeps))
    # The timeline's own rule, which the observation agrees with.
    with pytest.raises(ValueError, match="not at a reachable green choice point"):
        _corridor_timeline({**keeps, first + MOST: "switch"})


@cache
def _town() -> TrafficInput:
    composed = compose_specified_world(TOWN, None, TOWN_WORLD)
    return traffic_input(
        world_id=TOWN_WORLD,
        version_id=composed.receipt_sha256,
        city_identity=composed.receipt["subject_identity"],
        grammar_version=composed.receipt["grammar"]["grammar_version"],
        records=composed.records,
    )


def _signals() -> tuple[str, ...]:
    return tuple(sorted(row["signal_id"] for row in compute_signal_catalog(wire(_town()))))


def _play(answer, signals: tuple[str, ...]) -> tuple[dict, list[dict], list[tuple[str, int]]]:
    """The episode's first seconds with every choice point of ``signals`` answered by
    ``answer(offered_so_far, point)``, as the controller answers them: recorded, then probed
    again from the continuation the probe stopped at."""
    value = _town()
    choices: dict[str, dict[int, str]] = {}
    continuation = None
    states: list[dict] = []
    offered: list[tuple[str, int]] = []
    while True:
        found = compute_signal_probe(wire(value), 0, SECONDS, continuation, choices, {}, signals)
        states.extend(found["states"])
        continuation = found["continuation"]
        point = found["point"]
        if point is None:
            return continuation, states, offered
        offered.append((point["signal_id"], point["choice_second"]))
        choices.setdefault(point["signal_id"], {})[point["choice_second"]] = answer(
            len(offered), point
        )


def test_a_model_that_always_keeps_green_is_never_offered_an_unreachable_second():
    signal = _signals()[0]
    continuation, _states, offered = _play(lambda _n, _point: "keep", (signal,))
    kept = sorted(int(second) for second in continuation["signal_choices"][signal])
    # Twelve keeps from 302 fill the green; 314, where amber must follow, is never offered.
    assert list(range(302, 302 + MOST)) == [second for second in kept if second >= 302]
    assert (signal, 302 + MOST) not in offered
    assert continuation["next_second"] == SECONDS


@pytest.mark.parametrize(
    ("pattern", "continuation_sha256", "states_sha256", "offered"),
    [
        (
            "switch",
            "7da45d174a50234d1cf544e56e8d54900627fb753725eac7fcf132449ab42ee1",
            "c0448e4ce5b16216c312bad69493452e08d8df9c36fe3f542a3e07d7024b97db",
            9,
        ),
        (
            "alternate",
            "19704c3408b608d354bc2abd9b913f2480fb1445c3c30422d0c740b5028604cf",
            "2ec8a0a7c222ec436172a78d6dc3d22251b94c31c4661d48829a8a97af02e0b7",
            18,
        ),
        (
            "keep_below_most",
            "da30119a36dcf8b8baa3c6ed33c4b8a9f1df9d3c45e569f6e29882784244990e",
            "b46a41640c1cbc1880ba667c69fd4fa1ff3f5fa77cbd8b3982fdafbf0fea9593",
            50,
        ),
    ],
)
def test_histories_that_never_fill_a_green_are_unchanged(
    pattern: str, continuation_sha256: str, states_sha256: str, offered: int
):
    """Every history a seal could already hold: answers that never keep a green past its last
    extension. Such a history plays to the same continuation and frames whether or not a filled
    green offers another choice, so the rule changes no sealed minute; the digests pin them."""

    def answer(count: int, point: dict) -> str:
        if pattern == "switch":
            return "switch"
        if pattern == "alternate":
            return "keep" if count % 2 else "switch"
        # Keep until the green's last extension would begin, then let it end.
        last = _minimum_green_seconds() + MOST - 1
        return "keep" if point["observation"]["green_elapsed_seconds"] < last else "switch"

    continuation, states, found = _play(answer, _signals())
    assert continuation["document_sha256"] == continuation_sha256
    assert hashlib.sha256(canonical_json(states)).hexdigest() == states_sha256
    assert len(found) == offered
