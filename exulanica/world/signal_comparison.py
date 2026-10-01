"""One run of a signal comparison: a saved town's traffic for one episode, its lights decided by one
arm.

A signal comparison asks what a town's traffic does when a model decides its signals' greens,
beside the same traffic under the signal plan's own fixed timing. Every run of it plays one
episode of the town's own roads as the traffic step plays it (:mod:`exulanica.world.
traffic_episodes`): the same roads and fleet, every vehicle leaving home at the second the
episode's index draws from the roads' own seed and staying where it went for the dwell drawn
there, so every arm of one seed starts from the same departures. Where a vehicle goes depends on
the places free when it leaves, and it is called home a dwell after it arrives, so its later trips
follow each arm's own traffic. The seed names the episode (:func:`episode_of`).

A run's arm names who decides for the comparison's group of signals: the plan's fixed timing, or a
model asked at every choice point the step offers (a green at its minimum or one extension past
it, with a vehicle near), as the live controller asks the owner's chosen model. A signal outside
the group keeps fixed timing in every arm. The step alone decides what a recorded answer does: an
accepted ``keep`` extends that green by one second, and anything else, a switch, a refusal, a late
or failed ask, lets the green end as the plan does.

What is measured is the traffic step's own authority (:mod:`exulanica.traffic.metrics`): for each
signal of the group, the vehicles that entered its junction and the delay each entry took, summed
exactly in milliseconds, and the episode's trips. The comparison's measure of a run is the mean
delay per entry at the group's junctions, as an exact fraction, beside the trips, never folded into
them and never on a person's scale. Cars in these episodes do not see walkers: the episodes are the
legacy ones, whose crossing feed is empty (``crossings_fed: false``).

Asking is not done here. :func:`play` takes an :class:`Asking` port; the host's runner asks a model
through it, and :func:`replay` answers from what a run stored, with no client at all, then holds
every rebuilt request to the stored bytes and the episode's end and its measure to what the run
recorded. A replay that differs is refused by name (:class:`ReplayMismatch`). Nothing here reads
or writes a database, a store or the live world.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from exulanica.canonical import canonical_json
from exulanica.traffic.metrics import MetricsAccumulator
from exulanica.world.decision_roles import DecisionContract, DecisionRole
from exulanica.world.role_decisions import (
    ReplayMismatch,
    role_receipt,
    role_request,
    seal,
    validate_role_receipt,
)
from exulanica.world.traffic_episodes import (
    EPISODE,
    TrafficInput,
    compute_signal_probe,
    prepared,
    wire,
)

__all__ = [
    "DECIDER_KINDS",
    "OBSERVATION_PROFILE",
    "Asking",
    "PlayedSignalRun",
    "ReplayMismatch",
    "SignalRunPlan",
    "episode_of",
    "measure",
    "play",
    "replay",
    "request_id",
]

#: Who decides for a run's group of signals: the plan's fixed timing, or a model.
DECIDER_KINDS: Final = ("fixed", "model")
#: The observation a signal's decision request is asked over, as the live controller seals it.
OBSERVATION_PROFILE: Final = "exulanica.junction-signal-observation/v1"
#: The episode index a seed names is drawn from this many leading hex digits of a SHA-256 of the
#: seed under :data:`_EPISODE_DOMAIN`: enough that one seed's episode says nothing of another's.
_EPISODE_HEX_DIGITS: Final = 12
#: What the seed is hashed under to name its episode. A catalog commits a held-out seed by the
#: SHA-256 of its text alone, so an episode drawn from that same digest would be known, with every
#: trip it draws, before the seed is revealed; under this prefix it cannot be computed without the
#: seed's text.
_EPISODE_DOMAIN: Final = b"exulanica.signal-comparison-episode/v1:"
#: The seed a signal's request is built with: the live controller's, so a comparison's requests
#: are made exactly as the live world's are (the signal role draws nothing from it).
_REQUEST_SEED: Final = "0" * 64


def episode_of(seed: str) -> int:
    """The episode a seed names: its trips are drawn from the roads' own seed and this index,
    which the seed's committed digest does not reveal."""
    digest = hashlib.sha256(_EPISODE_DOMAIN + seed.encode("utf-8")).hexdigest()
    return int(digest[:_EPISODE_HEX_DIGITS], 16)


def request_id(run_id: uuid.UUID, signal_id: str, choice_second: int) -> uuid.UUID:
    """The request a signal is asked with at one choice point of one run."""
    return uuid.uuid5(run_id, f"signal-decision:{signal_id}:{choice_second}")


@dataclass(frozen=True, slots=True)
class SignalRunPlan:
    """Everything one run depends on, all of it recorded with the comparison it belongs to."""

    run_id: uuid.UUID
    #: The saved world's roads, exactly: the comparison records their digest and version.
    roads: TrafficInput
    seed: str
    #: The signals every arm decides for, by identity: the group.
    group: tuple[str, ...]
    #: The arm's decider for every signal of the group.
    decider: Mapping[str, Any]
    #: What a model arm's requests record about the model they ask; None for fixed timing.
    provider_config: Mapping[str, Any] | None
    role: DecisionRole
    contract: DecisionContract

    def __post_init__(self) -> None:
        kind = self.decider.get("kind")
        if kind not in DECIDER_KINDS:
            raise ValueError(f"no signal decider {kind!r}")
        if (kind == "model") != (self.provider_config is not None):
            raise ValueError("exactly a model arm records what its requests ask")
        if not self.group or list(self.group) != sorted(set(self.group)):
            raise ValueError("a group names each signal once, in identity order")

    @property
    def episode(self) -> int:
        return episode_of(self.seed)

    @property
    def chosen(self) -> tuple[str, ...]:
        """The signals asked at their choice points: the group under a model, none under fixed."""
        return self.group if self.decider["kind"] == "model" else ()


class Asking(Protocol):
    """What a run asks of the world outside it, one choice point at a time."""

    def answer(self, request: dict[str, Any]) -> dict[str, Any]:
        """The result a receipt records for ``request``: its status, reason, proposal and the
        provider's record of the call."""
        ...


@dataclass(slots=True)
class _Measure:
    """The traffic step's own measure of a run, accumulated second by second."""

    accumulator: MetricsAccumulator
    group_junctions: Mapping[str, str]

    def observe(self, state: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> None:
        self.accumulator.observe(state, events)


@dataclass(slots=True)
class PlayedSignalRun:
    """What a run did: its episode's last continuation, its measure's integer terms, and every
    request and receipt of its choice points, in the order they were asked."""

    continuation: dict[str, Any]
    terms: dict[str, Any]
    requests: list[dict[str, Any]] = field(default_factory=list)
    receipts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def continuation_sha256(self) -> str:
        return str(self.continuation["document_sha256"])

    @property
    def receipts_sha256(self) -> str:
        return hashlib.sha256(
            canonical_json([receipt["document_sha256"] for receipt in self.receipts])
        ).hexdigest()


def _group_junctions(roads: TrafficInput, group: Sequence[str]) -> dict[str, str]:
    """Each signal of the group by the junction it stands at, refused by name where the roads
    compile no such signal."""
    network = prepared(roads).network
    placed = {
        junction.signal.identity: identity
        for identity, junction in network.junctions.items()
        if junction.signal is not None
    }
    missing = sorted(set(group) - set(placed))
    if missing:
        raise ValueError(f"signal_not_in_world: {missing}")
    return {signal: placed[signal] for signal in group}


def _terms(measure: _Measure, continuation: Mapping[str, Any]) -> dict[str, Any]:
    """The run's measure as integers: each group signal's entries and summed delay at its
    junction, the group's totals, and what the episode's trips came to."""
    accumulator = measure.accumulator
    signals = [
        {
            "signal_id": signal,
            "junction_id": junction,
            "entries": int(accumulator.entries[junction]),
            "delay_ms": int(accumulator.delay_ms[junction]),
        }
        for signal, junction in sorted(measure.group_junctions.items())
    ]
    final = continuation["state"]
    trips = final["trips"]
    arrived = [trip for trip in trips if trip["status"] == "arrived"]
    blocked: dict[str, int] = {}
    for trip in trips:
        if trip["status"] == "blocked":
            blocked[trip["reason"]] = blocked.get(trip["reason"], 0) + 1
    return {
        "profile": "exulanica.signal-comparison-terms/v1",
        "seconds": int(accumulator.seconds),
        "signals": signals,
        "entries": sum(row["entries"] for row in signals),
        "delay_ms": sum(row["delay_ms"] for row in signals),
        "trips": {
            "requested": len(trips),
            "arrived": len(arrived),
            "blocked": dict(sorted(blocked.items())),
            "unfinished": len(trips) - len(arrived) - sum(blocked.values()),
            "door_to_door_seconds": sum(
                int(trip["arrived_second"]) - int(trip["requested_second"]) for trip in arrived
            ),
        },
        "vehicles_away_at_end": sum(
            1 for vehicle in final["vehicles"] if vehicle["mode"] != "parked"
        ),
    }


def measure(terms: Mapping[str, Any]) -> tuple[int, int] | None:
    """A run's measure, the mean delay per entry at the group's junctions, as its exact numerator
    and denominator in milliseconds and entries, or None where no vehicle entered them."""
    if int(terms["entries"]) == 0:
        return None
    return int(terms["delay_ms"]), int(terms["entries"])


def _request(plan: SignalRunPlan, point: Mapping[str, Any]) -> dict[str, Any]:
    """The request a signal is asked with at a choice point: the role's own, over the observation
    the live controller seals, with the choice's second as its tick."""
    second = int(point["choice_second"])
    signal = str(point["signal_id"])
    source = seal(
        {
            "profile": OBSERVATION_PROFILE,
            "world_id": plan.roads.world_id,
            "roads_version": plan.roads.version_id,
            "episode": plan.episode,
            "segment": second // 60,
            "choice_generation": 1,
            "choice_second": second,
            "signal_id": signal,
            "state_sha256": point["state_sha256"],
            "observation": dict(point["observation"]),
            "input_seq": 1,
        }
    )
    state = {
        "branch_id": str(plan.run_id),
        "tick": second,
        "signals": [signal],
        "choice_points": [signal],
    }
    request, status = role_request(
        plan.role,
        state,
        source,
        signal,
        request_id=request_id(plan.run_id, signal, second),
        contract=plan.contract,
        seed=_REQUEST_SEED,
        provider_config=dict(plan.provider_config or {}),
    )
    if request is None:
        raise ValueError(f"no request could be made at a choice point: {status}")
    return request


def _action(receipt: Mapping[str, Any]) -> str:
    """What a receipt does to its green: an accepted answer's kind, else the plan's switch."""
    if receipt["status"] != "accepted":
        return "switch"
    return str(receipt["proposal"]["option"]["kind"])


def play(
    plan: SignalRunPlan,
    asking: Asking,
    *,
    on_point: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
) -> PlayedSignalRun:
    """Play ``plan``'s episode, asking ``asking`` at every choice point of a model arm's group.

    ``on_point(request, receipt)`` is called with each answered point before the episode goes on,
    so a caller can store what it paid for as it goes.
    """
    data = wire(plan.roads)
    counted = _Measure(
        MetricsAccumulator(prepared(plan.roads).network), _group_junctions(plan.roads, plan.group)
    )
    choices: dict[str, dict[int, str]] = {}
    continuation: dict[str, Any] | None = None
    played_requests: list[dict[str, Any]] = []
    played_receipts: list[dict[str, Any]] = []
    while True:
        found = compute_signal_probe(
            data,
            plan.episode,
            EPISODE,
            continuation,
            choices,
            {},
            plan.chosen,
            observe=counted.observe,
        )
        continuation = found["continuation"]
        point = found["point"]
        if point is None:
            break
        request = _request(plan, point)
        receipt = role_receipt(
            plan.role, request, len(played_receipts) + 1, dict(asking.answer(request))
        )
        validate_role_receipt(plan.role, receipt, request)
        if on_point is not None:
            on_point(request, receipt)
        played_requests.append(request)
        played_receipts.append(receipt)
        choices.setdefault(str(point["signal_id"]), {})[int(point["choice_second"])] = _action(
            receipt
        )
    assert continuation is not None
    return PlayedSignalRun(
        continuation=continuation,
        terms=_terms(counted, continuation),
        requests=played_requests,
        receipts=played_receipts,
    )


@dataclass(slots=True)
class _Stored:
    """Answers from what a run stored, each held to the request its receipt answers."""

    requests: Mapping[str, dict[str, Any]]
    receipts: Mapping[str, dict[str, Any]]
    used: set[str]

    def answer(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request["request_id"])
        stored, receipt = self.requests.get(key), self.receipts.get(key)
        if stored is None or receipt is None:
            raise ReplayMismatch("a rebuilt choice point has no stored answer")
        if stored != request or receipt["request_sha256"] != request["document_sha256"]:
            raise ReplayMismatch("a rebuilt request is not the one stored")
        self.used.add(key)
        return {key: receipt[key] for key in ("status", "reason", "proposal", "provider")}


def replay(
    plan: SignalRunPlan,
    stored: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]],
    *,
    continuation_sha256: str,
    terms: Mapping[str, Any],
) -> PlayedSignalRun:
    """Play ``plan`` again from the requests and receipts it stored, asking nothing, and hold it to
    its record: every rebuilt request and receipt to the stored bytes, the episode's last
    continuation to ``continuation_sha256`` and its measure to ``terms``."""
    requests = {str(request["request_id"]): dict(request) for request, _ in stored}
    receipts = {str(receipt["request_id"]): dict(receipt) for _, receipt in stored}
    if len(requests) != len(stored) or len(receipts) != len(stored):
        raise ReplayMismatch("a choice point is stored twice")
    answering = _Stored(requests, receipts, set())
    played = play(plan, answering)
    if played.continuation_sha256 != continuation_sha256:
        raise ReplayMismatch("the episode ends in another state")
    if played.terms != dict(terms):
        raise ReplayMismatch("the episode's measure is not the one recorded")
    if [dict(receipt) for _, receipt in stored] != played.receipts:
        raise ReplayMismatch("a stored receipt is not the one its request rebuilds")
    if answering.used != set(receipts):
        raise ReplayMismatch("a stored receipt answers no choice point the run meets")
    return played
