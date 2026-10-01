"""A signal comparison's run, played and replayed: pure, with no database and no model.

One generated small town's roads, both of its signals in the group. The fixed-timing arm asks
nobody; a model arm is asked at every choice point the traffic step offers, here by scripted
answers. Always letting the green end is the plan's own timing, so it measures exactly what fixed
timing measures; keeping greens changes the waiting but never the departures, which every arm of
one seed starts from alike. A run replays from what it stored, asking nothing, and a replay that
differs from its record is refused by name.
"""

from __future__ import annotations

import hashlib
import uuid
from functools import cache
from typing import Any

import pytest
from exulanica.world.decision_roles import decision_roles
from exulanica.world.generated_worlds import compose_specified_world
from exulanica.world.signal_comparison import (
    PlayedSignalRun,
    ReplayMismatch,
    SignalRunPlan,
    episode_of,
    measure,
    play,
    replay,
)
from exulanica.world.society import seed_digest
from exulanica.world.traffic_episodes import (
    TrafficInput,
    compute_signal_catalog,
    traffic_input,
    wire,
)

WORLD_ID = "world:generated:v7-signal-comparison-small_town-0"
SEED = hashlib.sha256(b"v7 signal comparison play: first seed").hexdigest()
OTHER = hashlib.sha256(b"v7 signal comparison play: second seed").hexdigest()


@cache
def _roads() -> TrafficInput:
    composed = compose_specified_world("small_town", None, WORLD_ID)
    return traffic_input(
        world_id=WORLD_ID,
        version_id=composed.receipt_sha256,
        city_identity=composed.receipt["subject_identity"],
        grammar_version=composed.receipt["grammar"]["grammar_version"],
        records=composed.records,
    )


def _plan(kind: str, seed: str = SEED) -> SignalRunPlan:
    role = decision_roles().deciding_for("signal")
    contract = role.contract()
    roads = _roads()
    config = {
        "provider": "scripted",
        "model_id": "scripted-signal-model",
        "mechanism": "tool_call",
        "choice_seq": None,
        "manifest_sha256": "a" * 64,
        "prompt_version": role.prompt_version,
        "contract": contract.binding(),
        "deadline_ms": contract.value("decision_deadline_ms"),
    }
    return SignalRunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"v7-signal-play:{kind}:{seed}"),
        roads=roads,
        seed=seed,
        group=tuple(sorted(row["signal_id"] for row in compute_signal_catalog(wire(roads)))),
        decider={"kind": kind},
        provider_config=None if kind == "fixed" else config,
        role=role,
        contract=contract,
    )


class _Nobody:
    """The fixed-timing arm's asking: it is never asked."""

    def answer(self, request: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("a fixed-timing run asks nobody")


class _Scripted:
    """A model that answers every point it is offered by ``choose(request)``, a kind of option."""

    def __init__(self, choose) -> None:
        self.choose = choose

    def answer(self, request: dict[str, Any]) -> dict[str, Any]:
        kind = self.choose(request)
        option = next(o for o in request["context"]["options"] if o["kind"] == kind)
        return {
            "status": "accepted",
            "reason": "validated_choice",
            "proposal": {"label": option["label"], "option": option},
            "provider": None,
        }


def _switch(_request: dict[str, Any]) -> str:
    return "switch"


def _keep_on_even_seconds(request: dict[str, Any]) -> str:
    """Keep a green at an even second and let it end at the next: one extension at most each."""
    return "keep" if request["context"]["choice_second"] % 2 == 0 else "switch"


@cache
def _fixed(seed: str = SEED) -> PlayedSignalRun:
    return play(_plan("fixed", seed), _Nobody())


@cache
def _kept() -> PlayedSignalRun:
    return play(_plan("model"), _Scripted(_keep_on_even_seconds))


def _departures(run: PlayedSignalRun) -> dict[str, int]:
    """When each vehicle first left home: the second the episode drew for it."""
    first: dict[str, int] = {}
    for trip in run.continuation["state"]["trips"]:
        vehicle, second = trip["vehicle_id"], int(trip["requested_second"])
        first[vehicle] = min(second, first.get(vehicle, second))
    return first


def test_a_seed_names_an_episode_its_committed_digest_does_not_reveal():
    assert episode_of(SEED) == episode_of(SEED) != episode_of(OTHER)
    # A catalog commits a held-out seed by this digest: the episode is not read off it.
    assert episode_of(SEED) != int(seed_digest(SEED)[:12], 16)


def test_letting_every_green_end_measures_exactly_what_fixed_timing_does():
    switched = play(_plan("model"), _Scripted(_switch))
    fixed = _fixed()
    # The positive control: the model arm was offered points, and the fixed arm none.
    assert switched.receipts and not fixed.receipts
    assert {receipt["status"] for receipt in switched.receipts} == {"accepted"}
    assert switched.terms == fixed.terms
    assert measure(fixed.terms) == (fixed.terms["delay_ms"], fixed.terms["entries"])


def test_every_arm_of_a_seed_starts_from_the_same_departures_and_another_seed_others():
    kept, fixed = _kept(), _fixed()
    kept_points = sum(
        1 for receipt in kept.receipts if receipt["proposal"]["option"]["kind"] == "keep"
    )
    assert kept_points > 0, "the scripted model kept some greens"
    assert kept.terms != fixed.terms, "keeping greens changed the waiting"
    assert _departures(kept) and _departures(kept) == _departures(fixed)
    assert _departures(_fixed(OTHER)) != _departures(fixed)


def test_a_run_replays_from_what_it_stored_and_a_record_it_differs_from_is_refused():
    plan, kept = _plan("model"), _kept()
    stored = list(zip(kept.requests, kept.receipts, strict=True))
    again = replay(plan, stored, continuation_sha256=kept.continuation_sha256, terms=kept.terms)
    assert again.receipts == kept.receipts
    assert again.continuation_sha256 == kept.continuation_sha256
    with pytest.raises(ReplayMismatch, match="no stored answer"):
        replay(plan, stored[1:], continuation_sha256=kept.continuation_sha256, terms=kept.terms)
    with pytest.raises(ReplayMismatch, match="measure"):
        replay(
            plan,
            stored,
            continuation_sha256=kept.continuation_sha256,
            terms={**kept.terms, "delay_ms": kept.terms["delay_ms"] + 1},
        )
