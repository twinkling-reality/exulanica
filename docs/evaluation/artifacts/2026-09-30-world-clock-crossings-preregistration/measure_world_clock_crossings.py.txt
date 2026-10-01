#!/usr/bin/env python3
"""Pre-register, then run, the held-out check that a coupled town's cars yield to its walkers.

    uv run python scripts/measure_world_clock_crossings.py --preregister --out PREREGISTRATION
    uv run python scripts/measure_world_clock_crossings.py --preregistration PREREGISTRATION \
        --out RECORD

Pure: no database, no store and no model. Each town is a generated world of a held-out identity,
never used while the clock was developed. For each, the living town (``exulanica-society/v5``)
walks its own place from 06:00; after ``WARM_MINUTES`` a coupled era begins, and every minute of
it records its crossing occupancy as a coupled world's society repository records it
(``minute_occupancy``). The town's traffic then drives each episode of the era with the feeds that
occupancy projects (``crossing_feeds``), from each episode's genesis as a coupled world's follower
does, and the independent traffic checker judges every transition against those feeds. The stress
arm drives one episode of some towns again with a planted stream of walkers far past the envelope.

What the pre-registration fixes before any held-out town is made: the identities, the presets,
the minutes, the envelope ``E(W, G)`` and the bound ``B``, the rule that classes a wait inside or
outside the envelope, the stress design and the pass rules, and this script's own digest. A run
refuses a pre-registration that binds other bytes of this script or states other values.

The record states measured results only for what it ran. It is not a timing measurement: nothing
is timed, and it runs on any machine.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import subprocess
import sys
import uuid
from collections import Counter
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.traffic.checks import TransitionChecker
from exulanica.traffic.inputs import (
    LOOKAHEAD_S,
    CrossingEntry,
    CrossingFeed,
    TrafficInputs,
    TripRequest,
)
from exulanica.world.authored_delta import AlternateVersion, version_delta_sha256
from exulanica.world.composers import GeneratedWorldRefused
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.society import world_society_seed
from exulanica.world.society_authored_ground import StandingPolicy, authored_ground_from_snapshot
from exulanica.world.society_living import (
    LIVING_TOWN_PROFILE,
    advance_living_society,
    initial_living_society,
    input_routine,
    living_places,
    town_routine,
)
from exulanica.world.society_walking_surfaces import (
    build_walking_surfaces_input,
    walking_surfaces_place,
)
from exulanica.world.traffic_episodes import (
    EPISODE,
    home_segment,
    prepared,
    road_records,
    traffic_input,
)
from exulanica.world.world_clock import (
    Era,
    crossing_edges,
    crossing_feeds,
    envelope_report,
    minute_occupancy,
    occupancy_intervals,
)
from exulanica.world.world_recipes import town_recipe

ROOT: Final = Path(__file__).resolve().parents[1]
KIND: Final = "exulanica.world-clock-crossings/v1"
PREREGISTRATION_KIND: Final = "exulanica.world-clock-crossings-preregistration/v1"
PROFILE: Final = "exulanica.digest-bound-record/v1"
#: The held-out towns: two presets, six identities each, none of them met in development.
PRESETS: Final = ("small_town", "market_town")
IDENTITIES: Final = 6
#: The town's day starts at 06:00; the era begins at 08:00 and runs two hours.
WARM_MINUTES: Final = 120
MEASURED_MINUTES: Final = 120
#: Traffic's timeline origin for every town's era: any whole episode serves.
ORIGIN: Final = 1_000 * EPISODE
#: The envelope and the bound.
WINDOW_SECONDS: Final = 180
GAP_SECONDS: Final = 62
WAIT_BOUND_SECONDS: Final = 240
#: The stress arm: the first episode of the first two identities of each preset, every band
#: occupied 15 seconds in every 20 from the episode's second minute.
STRESS_IDENTITIES: Final = 2
STRESS_PERIOD_SECONDS: Final = 20
STRESS_OCCUPIED_SECONDS: Final = 15
#: What the stress arm's society ids are, a label, not a person.
STRESS_SOURCE: Final = "planted stress walker"
WORKSPACE: Final = uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/w7-held-out-workspace")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def script_sha256() -> str:
    return _sha256(Path(__file__).read_bytes())


def identities() -> list[dict[str, str]]:
    return [
        {"preset": preset, "world_id": f"world:generated:w7-held-out-{preset}-{number}"}
        for preset in PRESETS
        for number in range(1, IDENTITIES + 1)
    ]


def design() -> dict[str, Any]:
    """Everything the pre-registration freezes, and a run holds itself to."""
    return {
        "question": (
            "On held-out generated towns whose clock is coupled, does traffic driven by the crossing "
            "occupancy the living town records ever let a vehicle's body meet a crossing a walker "
            "is on, and inside a declared demand envelope do vehicles waiting for walkers go on "
            "within a bound?"
        ),
        "towns": identities(),
        "society": {
            "engine": LIVING_TOWN_PROFILE,
            "seed_rule": "world_society_seed of the town's world id in a fixed evaluation workspace",
            "workspace": str(WORKSPACE),
            "starts": "06:00",
            "warm_minutes": WARM_MINUTES,
            "measured_minutes": MEASURED_MINUTES,
        },
        "traffic": {
            "timeline_origin_second": ORIGIN,
            "episodes": MEASURED_MINUTES * 60 // EPISODE,
            "lookahead_seconds": LOOKAHEAD_S,
            "judge": "exulanica.traffic.checks.TransitionChecker over every transition, against the feeds",
        },
        "envelope": {
            "window_seconds": WINDOW_SECONDS,
            "gap_seconds": GAP_SECONDS,
            "wait_bound_seconds": WAIT_BOUND_SECONDS,
            "rule": (
                "a crossing is inside the envelope over a span when every window of window_seconds "
                "starting in it holds a run of at least gap_seconds with no walker on the crossing; a "
                "vehicle's wait for walkers (consecutive seconds whose wait reason is pedestrian_due) "
                "is inside the envelope when every crossing of the town is inside it over the span "
                "from window_seconds before the wait began to the wait's last second"
            ),
        },
        "stress": {
            "identities_per_preset": STRESS_IDENTITIES,
            "episode": "the era's first",
            "period_seconds": STRESS_PERIOD_SECONDS,
            "occupied_seconds": STRESS_OCCUPIED_SECONDS,
            "from_local_second": 60,
            "bands": "every band of the town's roads",
        },
        "pass_rules": {
            "P1": "no checker violation of any kind in any town or stress run",
            "P2": (
                "every wait for walkers inside the envelope lasts at most wait_bound_seconds, and no "
                "trip is blocked for pedestrian_due whose wait began inside the envelope"
            ),
            "P3": "every crossing a town's walkers occupy is a band of its roads",
            "reported_not_judged": [
                "waits and blocked trips outside the envelope",
                "the stress arm's waits and blocked trips",
            ],
            "excluded": "a held-out identity the generator refuses is excluded and named, never replaced",
        },
    }


def tree_digest() -> dict[str, Any]:
    """The source the run read: HEAD, and a digest over every tracked or untracked, not ignored,
    file under ``exulanica`` and ``assets/catalogs`` as it is on disk."""
    head = subprocess.run(
        ["git", "--no-optional-locks", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    listed = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "ls-files",
            "-co",
            "--exclude-standard",
            "exulanica",
            "assets/catalogs",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    digest = hashlib.sha256()
    for relative in sorted(set(listed)):
        path = ROOT / relative
        if path.is_file():
            digest.update(relative.encode() + b"\0" + _sha256(path.read_bytes()).encode() + b"\n")
    return {"head": head, "files": len(set(listed)), "files_sha256": digest.hexdigest()}


def _write(path: Path, record: dict[str, Any]) -> str:
    body = {"profile": PROFILE, "record": record, "record_sha256": _sha256(canonical_json(record))}
    path.write_text(json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return body["record_sha256"]


def preregister(out: Path) -> None:
    artifacts = ROOT / "docs" / "evaluation" / "artifacts" / out.stem
    artifacts.mkdir(parents=True, exist_ok=True)
    copy = artifacts / f"{Path(__file__).stem}.py.txt"
    copy.write_bytes(Path(__file__).read_bytes())
    record = {
        "kind": PREREGISTRATION_KIND,
        "design": design(),
        "script_sha256": script_sha256(),
        "artifacts": [
            {
                "path": str(copy.relative_to(ROOT)),
                "sha256": _sha256(copy.read_bytes()),
                "byte_size": copy.stat().st_size,
                "is": "the script that writes this pre-registration and runs the held-out towns",
            }
        ],
        "tree": tree_digest(),
        "registered_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "written_before_any_held_out_run": True,
    }
    digest = _write(out, record)
    print(f"pre-registration {digest} written to {out.relative_to(ROOT)}")


# -- one town -------------------------------------------------------------------------------------


def _town(preset: str, world_id: str) -> tuple[dict[str, Any], Any]:
    """The town's society input, as the runtime composes it, and its traffic input."""
    recipe = town_recipe(preset, None)
    composed = compose_generated_world(recipe, world_id)
    snapshot_id = uuid.uuid5(uuid.NAMESPACE_URL, composed.receipt_sha256)
    ground = authored_ground_from_snapshot(
        world_id=world_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=composed.receipt_sha256,
        composer_key=composed.candidate.composer_key,
        composer_version=composed.candidate.composer_version,
        topology=composed.candidate.topology,
        placement=composed.candidate.placement,
    )
    routine = town_routine()
    policy = routine.policy
    empty = AlternateVersion(
        version_id=uuid.uuid5(uuid.NAMESPACE_URL, world_id),
        world_id=world_id,
        source_snapshot_id=snapshot_id,
        parent_version_id=None,
        title="held-out",
        style_version_id=None,
        state_sha256="0" * 64,
        edit_seq=0,
        source_invalidated=False,
        created_by=uuid.UUID(int=0),
        created_at="2026-09-30T00:00:00+00:00",
    )
    version = AlternateVersion(
        **{
            **{field: getattr(empty, field) for field in empty.__slots__},
            "state_sha256": version_delta_sha256(empty),
        }
    )
    document = build_walking_surfaces_input(
        ground=ground,
        version=version,
        place=walking_surfaces_place(ground.place_id, composed.records, routine),
        input_seq=1,
        dependency_refs=[],
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        standing=StandingPolicy(policy["standing_spacing_mm"], policy["standing_radius_mm"]),
        living=routine,
    )
    value = traffic_input(
        world_id=world_id,
        version_id=composed.receipt_sha256,
        city_identity=str(composed.receipt["subject_identity"]),
        grammar_version=int(composed.receipt["grammar"]["grammar_version"]),
        records=road_records(composed.records),
    )
    return document, value


def _walk(world_id: str, document: dict[str, Any]) -> tuple[Era, list[dict[str, Any]], int]:
    routine = input_routine(document)
    [place] = living_places([document], routine, {})
    society = uuid.uuid5(uuid.NAMESPACE_URL, f"https://exulanica.invalid/w7-held-out/{world_id}")
    seed = world_society_seed(WORKSPACE, world_id)
    state = initial_living_society(
        society,
        seed,
        place,
        routine,
        branch_id=document["version_id"],
        population=document["population"]["size"],
        profile=LIVING_TOWN_PROFILE,
    )
    for _ in range(WARM_MINUTES):
        state, _events = advance_living_society(state, seed, [place], routine)
    era = Era(1, state["tick"], 60, ORIGIN)
    edges = crossing_edges([place.document])
    documents = []
    # Two minutes past the measured span: the last episode's lookahead reaches into them.
    for _ in range(MEASURED_MINUTES + 2):
        before = state
        state, events = advance_living_society(state, seed, [place], routine)
        documents.append(
            minute_occupancy(
                society_id=str(society),
                era=1,
                before=before,
                after=state,
                events=[event.document for event in events],
                crossings_by_edge=edges,
                place_sha256=place.document["document_sha256"],
            )
        )
    return era, documents, document["population"]["size"]


def _drive(value: Any, ready: Any, episode: int, feeds: tuple[CrossingFeed, ...]) -> dict[str, Any]:
    """One episode from its genesis with ``feeds``, judged; its waits and trips."""
    states, continuation, summary, point = home_segment(
        value, ready, episode, EPISODE, None, feeds=feeds
    )
    assert point is None
    trips = tuple(TripRequest(**item) for item in continuation["trips"])
    checker = TransitionChecker(ready.network, ready.catalogs, TrafficInputs(trips, feeds))
    violations = Counter()
    for before, after in pairwise(states):
        for violation in checker.check(before, after):
            violations[violation.kind] += 1
    runs: list[dict[str, int]] = []
    open_runs: dict[str, int] = {}
    for state in states[1:]:
        second = state["second"]
        waiting = {v["id"] for v in state["vehicles"] if v["wait_reason"] == "pedestrian_due"}
        for vehicle in sorted(set(open_runs) - waiting):
            first = open_runs.pop(vehicle)
            runs.append({"from_local_second": first, "seconds": second - first})
        for vehicle in sorted(waiting - set(open_runs)):
            open_runs[vehicle] = second
    for _vehicle, first in sorted(open_runs.items()):
        runs.append({"from_local_second": first, "seconds": states[-1]["second"] - first + 1})
    blocked = [
        {"reason": trip["reason"], "blocked_second": trip["blocked_second"]}
        for trip in states[-1]["trips"]
        if trip["status"] == "blocked"
    ]
    return {
        "violations": dict(sorted(violations.items())),
        "waits": sorted(runs, key=lambda item: (item["from_local_second"], item["seconds"])),
        "blocked": blocked,
        "summary": summary,
        "vehicles": len(states[-1]["vehicles"]),
        "fed_entries": sum(len(feed.entries) for feed in feeds),
    }


def _outside(report: dict[str, Any]) -> list[list[int]]:
    """Every window start outside the envelope, over every crossing, as merged spans."""
    spans = sorted(
        (first, last)
        for crossing in report.values()
        for first, last in crossing["outside_window_starts"]
    )
    merged: list[list[int]] = []
    for first, last in spans:
        if merged and first <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], last)
        else:
            merged.append([first, last])
    return merged


def _inside(outside: list[list[int]], first: int, last: int) -> bool:
    """Whether every window starting from ``window_seconds`` before ``first`` to ``last`` is
    inside the envelope."""
    low = first - WINDOW_SECONDS
    return not any(start <= last and low <= end for start, end in outside)


def run_town(preset: str, world_id: str, stress: bool) -> dict[str, Any]:
    try:
        document, value = _town(preset, world_id)
    except GeneratedWorldRefused as refused:
        return {"preset": preset, "world_id": world_id, "excluded": str(refused)}
    ready = prepared(value)
    bands = {band.identity: band.society_crossing_id for band in ready.network.bands}
    era, documents, population = _walk(world_id, document)
    intervals = occupancy_intervals(documents)
    unmapped = sorted({i["crossing_id"] for i in intervals} - set(bands))
    result: dict[str, Any] = {
        "preset": preset,
        "world_id": world_id,
        "population": population,
        "bands": len(bands),
        "junction_bands": sum(1 for band in ready.network.bands if band.junction is not None),
        "occupancy_intervals": dict(sorted(Counter(i["basis"] for i in intervals).items())),
        "crossings_walked": len({i["crossing_id"] for i in intervals}),
        "unmapped_crossings": unmapped,
    }
    if unmapped:
        return result
    episodes = []
    first_episode = ORIGIN // EPISODE
    for episode in range(first_episode, first_episode + MEASURED_MINUTES * 60 // EPISODE):
        feeds = crossing_feeds(
            intervals,
            era=era,
            episode_first_second=episode * EPISODE,
            covers_through_local_second=EPISODE + LOOKAHEAD_S - 1,
            bands=bands,
        )
        by_band: dict[str, list[tuple[str, int, int]]] = {}
        for feed in feeds:
            for entry in feed.entries:
                by_band.setdefault(entry.crossing_id, []).append(
                    (entry.crossing_id, entry.arrival_second, entry.last_second)
                )
        # Judged over the episode and the lookahead its feed reaches into.
        report = envelope_report(
            [item for items in by_band.values() for item in items],
            start=0,
            end=EPISODE + LOOKAHEAD_S,
            window_seconds=WINDOW_SECONDS,
            gap_seconds=GAP_SECONDS,
        )
        outside = _outside(report)
        driven = _drive(value, ready, episode, feeds)
        waits = [
            {
                **run,
                "inside_envelope": _inside(
                    outside, run["from_local_second"], run["from_local_second"] + run["seconds"] - 1
                ),
            }
            for run in driven["waits"]
        ]
        blocked = []
        for trip in driven["blocked"]:
            began = trip["blocked_second"] - 300
            blocked.append(
                {
                    **trip,
                    "inside_envelope": trip["reason"] == "pedestrian_due"
                    and _inside(outside, began, trip["blocked_second"]),
                }
            )
        episodes.append(
            {
                "episode": episode,
                "violations": driven["violations"],
                "fed_entries": driven["fed_entries"],
                "trips": driven["summary"],
                "vehicles": driven["vehicles"],
                "outside_envelope_window_starts": outside,
                "longest_occupied_run_seconds": max(
                    (crossing["longest_occupied_run_seconds"] for crossing in report.values()),
                    default=0,
                ),
                "waits": waits,
                "blocked": blocked,
            }
        )
    result["episodes"] = episodes
    if stress:
        episode = first_episode
        entries = []
        for band in sorted(bands.values()):
            for arrival in range(60, EPISODE + LOOKAHEAD_S, STRESS_PERIOD_SECONDS):
                entries.append(CrossingEntry(band, arrival, STRESS_OCCUPIED_SECONDS, STRESS_SOURCE))
        entries.sort(key=lambda entry: (entry.arrival_second, entry.crossing_id, entry.source))
        feeds = []
        for seq in range(1, EPISODE // 60 + 1):
            low, high = (0 if seq == 1 else 60 * seq), 60 * seq + 59
            feeds.append(
                CrossingFeed(
                    seq, high, tuple(e for e in entries if low <= e.arrival_second <= high)
                )
            )
        driven = _drive(value, ready, episode, tuple(feeds))
        result["stress"] = {
            "episode": episode,
            "violations": driven["violations"],
            "trips": driven["summary"],
            "blocked_reasons": dict(
                sorted(Counter(t["reason"] for t in driven["blocked"]).items())
            ),
            "longest_wait_seconds": max((run["seconds"] for run in driven["waits"]), default=0),
            "waits": len(driven["waits"]),
        }
    return result


def judge(towns: list[dict[str, Any]]) -> dict[str, Any]:
    ran = [town for town in towns if "excluded" not in town]
    violations = Counter()
    for town in ran:
        for episode in town.get("episodes", []):
            violations.update(episode["violations"])
        if "stress" in town:
            violations.update(town["stress"]["violations"])
    inside_waits = [
        run["seconds"]
        for town in ran
        for episode in town.get("episodes", [])
        for run in episode["waits"]
        if run["inside_envelope"]
    ]
    outside_waits = [
        run["seconds"]
        for town in ran
        for episode in town.get("episodes", [])
        for run in episode["waits"]
        if not run["inside_envelope"]
    ]
    inside_blocked = [
        trip
        for town in ran
        for episode in town.get("episodes", [])
        for trip in episode["blocked"]
        if trip["inside_envelope"]
    ]
    unmapped = [town["world_id"] for town in ran if town["unmapped_crossings"]]
    p1 = not violations
    p2 = all(seconds <= WAIT_BOUND_SECONDS for seconds in inside_waits) and not inside_blocked
    p3 = not unmapped
    return {
        "P1": {"passed": p1, "violations": dict(sorted(violations.items()))},
        "P2": {
            "passed": p2,
            "inside_waits": len(inside_waits),
            "longest_inside_wait_seconds": max(inside_waits, default=0),
            "inside_blocked_for_walkers": len(inside_blocked),
        },
        "P3": {"passed": p3, "towns_with_unmapped_crossings": unmapped},
        "reported": {
            "outside_waits": len(outside_waits),
            "longest_outside_wait_seconds": max(outside_waits, default=0),
            "excluded_towns": [town["world_id"] for town in towns if "excluded" in town],
        },
        "passed": p1 and p2 and p3,
    }


def run(preregistration: Path, out: Path) -> None:
    registered = json.loads(preregistration.read_text())
    record = registered["record"]
    if (
        registered["profile"] != PROFILE
        or registered["record_sha256"] != _sha256(canonical_json(record))
        or record["kind"] != PREREGISTRATION_KIND
    ):
        raise SystemExit(
            "the pre-registration is not a digest-bound pre-registration of this check"
        )
    if record["script_sha256"] != script_sha256() or record["design"] != design():
        raise SystemExit("the pre-registration binds other bytes or values of this script")
    towns = []
    for index, town in enumerate(identities()):
        number = index % IDENTITIES
        towns.append(run_town(town["preset"], town["world_id"], stress=number < STRESS_IDENTITIES))
        print(f"{town['world_id']}: done", file=sys.stderr)
    result = {
        "kind": KIND,
        "answers": {
            "path": str(preregistration.relative_to(ROOT)),
            "record_sha256": registered["record_sha256"],
        },
        "script_sha256": script_sha256(),
        "tree": tree_digest(),
        "python": platform.python_version(),
        "towns": towns,
        "judgment": judge(towns),
        "limits": [
            "Mechanics on generated towns through the pure chain the coupled follower runs; the "
            "database path, its ordering and its sealing are held by tests, not by this record.",
            "The envelope judges the whole town at once: a wait counts as inside only when every "
            "crossing of the town is inside the envelope over its span.",
            "No timing is measured, and nothing here is a capacity or intelligence claim.",
        ],
        "written_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }
    digest = _write(out, result)
    print(f"record {digest} written to {out.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--preregister", action="store_true")
    parser.add_argument("--preregistration", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    out = arguments.out.resolve()
    if arguments.preregister:
        preregister(out)
    elif arguments.preregistration is not None:
        run(arguments.preregistration.resolve(), out)
    else:
        parser.error("name --preregister or --preregistration")


if __name__ == "__main__":
    main()
