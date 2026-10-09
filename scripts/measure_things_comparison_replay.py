#!/usr/bin/env python3
"""Measure what reading one completed run of a society of things' comparison costs, by its people.

    uv run python scripts/measure_things_comparison_replay.py preregister --out PREREGISTRATION
    .exulanica/bin/quiet-slot uv run python scripts/measure_things_comparison_replay.py run \\
        --preregistration PREREGISTRATION --repeats 5 --out RECORD

Pure: no database, no store and no model. The run route (``GET .../comparisons/{id}/runs/{run}``)
replays a completed run from the requests and receipts it stored, holds the replay to what the run
recorded and answers the document the page draws. ``scripts/measure_living_comparison_replay.py``
measures that replay for the living town; this measures it for a society of things
(``exulanica-society/v7``), whose minutes also run the things phase (lines said and heard, hands),
in the same form:

- **Graphs.** The grounds a society of things runs on, each composed through the path the runtime
  composes its input by: the Three strangers scene (:data:`SQUARE_SCENE`) on a bare starter, placed
  from the starter's spawn as a scene is placed (``exulanica.world.scenes.places``), as an
  authored-ground v5 input; and the town scene (:data:`TOWN_SCENE`) on a generated small town,
  placed from the town's arrival, as a walking-surfaces v3 input. Each also holds
  :data:`HOLDABLES` placed holdable things at fixed places (a grid on the square, walking-line
  nodes near the town's arrival), so a run's hands have things to act on.
- **Points.** On each graph, at each stated population (:data:`SQUARE_POPULATIONS`, and on the
  town :data:`TOWN_POPULATIONS` with its own), one hour nobody is decided for (the routine), one a
  model arm decides for everybody, and one for each stated group below the population
  (:data:`STATED_GROUPS`). Every run is played once with scripted answers the engine applies
  (:class:`_Acting`: a hands act or a said line whenever either is offered, else an option
  chosen by the request's digest), then read ``--repeats`` times as the
  route reads it: ``verified_replay``, ``replay_document`` and the JSON body. These are the most
  receipts, lines and hands acts such a run holds, not any model's behaviour.
- **Line.** From every point's 95th percentile read, the living measurement's least-margin line
  ``fixed + per_person x population + per_decided x decided + per_pair x population x decided``
  on or above every point, and from it and the protocol's pair budget the most people a comparison
  of a society of things runs and the most of them a model may decide for.

The design is fixed by ``preregister`` before any timed read: a digest-bound record of this
script's digest, the tree, the drawing digest, the files it reads beside the package and every
constant below. ``run`` refuses a pre-registration this script, tree or drawing digest does not
match. The machine gate is the living measurement's: at least 70 percent CPU idle over ten seconds
before the run (refused otherwise), the one-minute load under 8 before every point, and a record
whose mean idle falls under 50 percent is written with ``discard: true``. Run it inside
``.exulanica/bin/quiet-slot``. Every duration is in whole microseconds, every share a decimal
string, and the record in the digest-bound form every retained record takes.
"""

from __future__ import annotations

import argparse
import dataclasses
import functools
import hashlib
import json
import math
import os
import platform
import sys
import uuid
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

ROOT: Final = Path(__file__).resolve().parents[1]
# The tree this script measures, ahead of any installed copy of the package; the composition
# helpers the things tests use are read from the tree's tests.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from measure_comparison_replay import (  # noqa: E402
    IDLE_BEFORE_PERCENT,
    IDLE_MEAN_PERCENT,
    LOAD_MOST,
    idle_share,
    load_average,
    settled,
)
from measure_living_comparison_replay import (  # noqa: E402
    _fit,
    _microseconds,
    _percent,
    _refuse_machine_paths,
    _source,
    _spread,
)

from exulanica.abilities.registry import recorded_row  # noqa: E402
from exulanica.canonical import canonical_json  # noqa: E402
from exulanica.environment.district_geometry import segment_blocked  # noqa: E402
from exulanica.world.authored_delta import version_delta_sha256  # noqa: E402
from exulanica.world.generated_worlds import compose_generated_world  # noqa: E402
from exulanica.world.objects import ObjectOrigin, Transform  # noqa: E402
from exulanica.world.placed_things import PlacedThing, named_kind  # noqa: E402
from exulanica.world.scenes import SceneArrival, places, shipped_scenes  # noqa: E402
from exulanica.world.society_authored_ground import (  # noqa: E402
    StandingPolicy,
    authored_ground_from_snapshot,
)
from exulanica.world.society_catalogs import comparison_catalogs_for_engine  # noqa: E402
from exulanica.world.society_city_place import city_obstructions  # noqa: E402
from exulanica.world.society_comparison import RunPlan, genesis, play  # noqa: E402
from exulanica.world.society_comparison_drawing import (  # noqa: E402
    CODE_SHA256,
    decode,
    encode,
    with_names,
)
from exulanica.world.society_comparison_reading import PAIR_RUNS, ReadingBound  # noqa: E402
from exulanica.world.society_comparison_result import (  # noqa: E402
    protocol_value,
    replay_document,
    verified_replay,
)
from exulanica.world.society_decision_contract import person_role  # noqa: E402
from exulanica.world.society_living import current_routine  # noqa: E402
from exulanica.world.society_things import THINGS_PROFILE  # noqa: E402
from exulanica.world.society_walking_surfaces import (  # noqa: E402
    build_walking_surfaces_input,
    walking_surfaces_place,
)
from exulanica.world.starter import (  # noqa: E402
    AUTHORED_SPAWN_X_MM,
    AUTHORED_SPAWN_Y_MM,
    AUTHORED_SPAWN_YAW_MICRORADIANS,
    AUTHORED_SPAWN_Z_MM,
)
from exulanica.world.world_recipes import town_recipe  # noqa: E402

import things_society_support as things_support  # noqa: E402
from living_town_support import version_of  # noqa: E402

PROFILE: Final = "exulanica.digest-bound-record/v1"
KIND: Final = "exulanica.things-comparison-replay-measurement/v1"
PREREGISTRATION_KIND: Final = "exulanica.things-comparison-replay-preregistration/v1"
SCRIPT: Final = "scripts/measure_things_comparison_replay.py"
#: The scenes placed, by key and version: the starter's and the town's Three strangers.
SQUARE_SCENE: Final = ("three-strangers", 4)
TOWN_SCENE: Final = ("three-strangers-in-town", 1)
#: The generated town the town scene is placed in, one fixed identity.
TOWN_PRESET: Final = "small_town"
TOWN_WORLD_ID: Final = "world:generated:things-replay-measured-small_town"
#: Placed holdable things beside each scene's own, alternately of these shipped kinds.
HOLDABLES: Final = 16
HOLDABLE_KINDS: Final = (("sword", 3), ("lantern", 1))
#: The square's holdables: a grid behind the scene, across the starter's walkable square.
SQUARE_GRID_X_MM: Final = (-7_000, -5_000, -3_000, -1_000, 1_000, 3_000, 5_000, 7_000)
SQUARE_GRID_Z_MM: Final = (2_000, 6_000)
#: The town's holdables: on walking-line nodes nearest the town's arrival, at least this far from
#: each other and from the scene's things.
TOWN_APART_MM: Final = 3_000
#: Populations measured: the starter's society takes a stated population; the town's people are
#: its residents, so it is measured at its own population and the stated ones below it.
SQUARE_POPULATIONS: Final = (8, 16, 32, 64, 128)
TOWN_POPULATIONS: Final = (8, 16, 32)
#: The groups a model decides for, below each measured population.
STATED_GROUPS: Final = (4, 16)
#: The society bound v7's engine row states, which no point measures here: the record names the
#: largest population measured instead.
SOCIETY_BOUND: Final = 512
#: Lines said, in turn, wherever saying is offered: fixed, one line each, sharing few words.
LINES: Final = (
    "Good morning.",
    "Is that your sword?",
    "The well looks deep today.",
    "Shall we walk to the gate together?",
    "I have not seen you here before.",
    "Rain may come later this afternoon.",
    "Who built this square?",
    "My armour needs polishing again.",
)
#: The option kinds chosen first, in this order, where they are offered.
HANDS_FIRST: Final = ("pick_up", "give", "take", "put_down")
SAYING: Final = ("say_to", "say_all")
#: The files the run reads beside the package's code, bound by digest.
READS: Final = (
    "assets/catalogs/scenes/three-strangers.v4.json",
    "assets/catalogs/scenes/three-strangers-in-town.v1.json",
    "tests/things_society_support.py",
    "tests/living_square_support.py",
    "tests/living_town_support.py",
    "scripts/measure_living_comparison_replay.py",
    "scripts/measure_comparison_replay.py",
)
_SEED: Final = "7" * 64
_MODEL: Final = {
    "kind": "model",
    "provider": "nebius_token_factory",
    "model_id": "measured/scripted",
}
ROLE: Final = person_role()
CONTRACT: Final = ROLE.contract_for(THINGS_PROFILE)


def _origin() -> ObjectOrigin:
    return ObjectOrigin("authored", "fictional")


def _holdable(index: int, region_id: str, x_mm: int, y_mm: int, z_mm: int) -> PlacedThing:
    kind, version = HOLDABLE_KINDS[index % len(HOLDABLE_KINDS)]
    return PlacedThing(
        f"held-{index}",
        named_kind(kind, version),
        region_id,
        Transform(x_mm, y_mm, z_mm, 0, 1000),
        _origin(),
        False,
    )


def _scene_things(key: tuple[str, int], arrival: SceneArrival) -> list[PlacedThing]:
    """A shipped scene's things, placed from ``arrival`` as a scene is placed."""
    return [
        PlacedThing(
            thing_id,
            named_kind(kind["kind"], kind["version"]),
            arrival.region_id,
            pose,
            _origin(),
            False,
        )
        for thing_id, kind, pose in places(shipped_scenes()[key], arrival)
    ]


def square_things() -> list[PlacedThing]:
    """The starter's Three strangers, from the starter's spawn, and the square's holdables."""
    theta = AUTHORED_SPAWN_YAW_MICRORADIANS / 1_000_000
    arrival = SceneArrival(
        "starter",
        "region:starter",
        (AUTHORED_SPAWN_X_MM, AUTHORED_SPAWN_Y_MM, AUTHORED_SPAWN_Z_MM),
        (-math.sin(theta), -math.cos(theta)),
    )
    grid = [(x, z) for z in SQUARE_GRID_Z_MM for x in SQUARE_GRID_X_MM]
    return _scene_things(SQUARE_SCENE, arrival) + [
        _holdable(index, "region:starter", x, 0, z) for index, (x, z) in enumerate(grid)
    ]


def compose_square() -> dict[str, Any]:
    """The square graph: a bare starter holding the scene and the holdables, as an authored-ground
    v5 input of a society of things."""
    document = things_support.compose(square_things(), objects=())
    return _graph("square", "authored_starter", document, stated=SQUARE_POPULATIONS)


@functools.cache
def _town() -> tuple[Any, Any, dict[str, Any], Any, StandingPolicy]:
    composed = compose_generated_world(town_recipe(TOWN_PRESET), TOWN_WORLD_ID)
    snapshot_id = uuid.uuid5(uuid.NAMESPACE_URL, composed.receipt_sha256)
    ground = authored_ground_from_snapshot(
        world_id=TOWN_WORLD_ID,
        snapshot_id=snapshot_id,
        snapshot_sha256=composed.receipt_sha256,
        composer_key=composed.candidate.composer_key,
        composer_version=composed.candidate.composer_version,
        topology=composed.candidate.topology,
        placement=composed.candidate.placement,
    )
    routine = current_routine()
    policy = routine.policy
    standing = StandingPolicy(policy["standing_spacing_mm"], policy["standing_radius_mm"])
    place = walking_surfaces_place(ground.place_id, composed.records, routine)
    return composed, ground, place, version_of(TOWN_WORLD_ID, snapshot_id), standing


def _town_input(things: Sequence[PlacedThing]) -> dict[str, Any]:
    composed, ground, place, base, standing = _town()
    version = dataclasses.replace(base, things=tuple(things))
    version = dataclasses.replace(version, state_sha256=version_delta_sha256(version))
    return build_walking_surfaces_input(
        ground=ground,
        version=version,
        place=place,
        input_seq=1,
        dependency_refs=[],
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        standing=standing,
        things=True,
        segment_blocked=segment_blocked,
        obstructions=city_obstructions(composed.records),
    )


def town_things() -> list[PlacedThing]:
    """The town's Three strangers, from the town's arrival, and the town's holdables on the
    walking-line nodes nearest it."""
    composed, ground = _town()[0], _town()[1]
    arrival = composed.receipt["arrival"]
    at = SceneArrival(
        "generated",
        ground.region_id,
        (arrival["position_mm"][0], arrival["support_z_mm"], -arrival["position_mm"][1]),
        (arrival["facing_mm"][0], -arrival["facing_mm"][1]),
    )
    scene = _scene_things(TOWN_SCENE, at)
    x0, z0 = arrival["position_mm"][0], -arrival["position_mm"][1]
    nodes = _town_input(scene)["navigation"]["nodes"]
    nearest = sorted(
        nodes,
        key=lambda node: (
            (node["position_mm"][0] - x0) ** 2 + (node["position_mm"][1] - z0) ** 2,
            node["node_id"],
        ),
    )
    taken = [(thing.transform.x_mm, thing.transform.z_mm) for thing in scene]
    chosen: list[tuple[int, int]] = []
    for node in nearest:
        x, z = node["position_mm"]
        if all((x - a) ** 2 + (z - b) ** 2 >= TOWN_APART_MM**2 for a, b in taken + chosen):
            chosen.append((x, z))
        if len(chosen) == HOLDABLES:
            break
    if len(chosen) < HOLDABLES:
        raise SystemExit("refused: the town has too few walking-line nodes for its holdables")
    return scene + [
        _holdable(index, ground.region_id, x, arrival["support_z_mm"], z)
        for index, (x, z) in enumerate(chosen)
    ]


def compose_town() -> dict[str, Any]:
    """The town graph: the small town holding the town scene and the holdables, as a
    walking-surfaces v3 input of a society of things."""
    document = _town_input(town_things())
    own = int(document["population"]["size"])
    return _graph(
        "town",
        TOWN_PRESET,
        document,
        stated=tuple(sorted({own, *(p for p in TOWN_POPULATIONS if p < own)})),
    )


def _graph(key: str, ground: str, document: dict[str, Any], *, stated: tuple[int, ...]) -> dict:
    """A graph as the record states it, refused where any placed thing is unavailable or any of
    its affordances is unavailable for another reason than the scene's own trees."""
    unavailable = [
        item
        for item in document["unavailable_affordances"]
        if not item["object_id"].startswith("tree-")
    ]
    if document["availability"] != "available" or unavailable:
        raise SystemExit(f"refused: the {key} graph does not compose with every thing usable")
    if recorded_row(document["modules"], "hands") is None:
        raise SystemExit(f"refused: the {key} graph's society does not run the hands module")
    return {
        "key": key,
        "ground": ground,
        "profile": document["profile"],
        "world_id": document["world_id"],
        "input_document_sha256": document["document_sha256"],
        "nodes": len(document["navigation"]["nodes"]),
        "things": [
            {
                "thing_id": thing["placed_id"],
                "kind": thing["kind"]["kind"],
                "version": thing["kind"]["version"],
                "position_mm": thing["position_mm"],
            }
            for thing in document["things"]
        ],
        "unavailable_affordances": [
            [item["object_id"], item["affordance"], item["reason"]]
            for item in document["unavailable_affordances"]
        ],
        "populations": list(stated),
        "document": document,
    }


class _Acting:
    """Answers every request with one of its own offered options: a hands act or a said line
    whenever either is offered (which first, by the request's digest), else the option the
    request's digest chooses, so the engine applies each and the run holds receipts, lines and
    acts at every choice point that offers them."""

    def __init__(self) -> None:
        self.said = 0

    def offerable(self, tick: int, due: Any) -> dict[str, frozenset[str]]:
        return {subject: frozenset(o.label for o in options) for subject, options in due.items()}

    def answers(self, requests: Any) -> list[dict[str, Any]]:
        results = []
        for request in requests:
            options = request["context"]["options"]
            digest = int(request["document_sha256"][:12], 16)
            # Hands first for half the requests and saying first for the other half, by digest,
            # so a run holds both wherever both are offered.
            first = (*HANDS_FIRST, *SAYING) if digest % 2 == 0 else (*SAYING, *HANDS_FIRST)
            option = next(
                (o for kind in first for o in options if o["kind"] == kind),
                options[digest % len(options)],
            )
            proposal: dict[str, Any] = {"label": option["label"], "option": option}
            if option["kind"] in SAYING:
                proposal["line"] = LINES[self.said % len(LINES)]
                self.said += 1
            results.append(
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": proposal,
                    "provider": None,
                }
            )
        return results


def _config() -> dict[str, Any]:
    return {
        "provider": _MODEL["provider"],
        "model_id": _MODEL["model_id"],
        "mechanism": "tool_call",
        "choice_seq": None,
        "manifest_sha256": "0" * 64,
        "prompt_version": ROLE.terms(THINGS_PROFILE).prompt_version,
        "contract": CONTRACT.binding(),
        "deadline_ms": CONTRACT.value("decision_deadline_ms"),
    }


def _plans(graph: dict[str, Any], population: int, window: int) -> list[tuple[int, RunPlan]]:
    """The runs measured at ``population`` on ``graph``: the routine, each stated group below the
    society's people and everybody, each with the number of people a model decides for."""
    base = {
        "society_id": uuid.uuid5(uuid.NAMESPACE_URL, graph["world_id"]),
        "seed": _SEED,
        "population": population,
        "inputs": (graph["document"],),
        "ticks": window,
        "contract": CONTRACT,
        "engine_profile": THINGS_PROFILE,
    }

    def run_id(decided: str) -> uuid.UUID:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"{graph['world_id']}:{population}:{decided}")

    routine = RunPlan(
        run_id=run_id("routine"), decider={"kind": "routine"}, provider_config=None, **base
    )
    people = sorted(person["id"] for person in genesis(routine)["inhabitants"])
    plans = [(0, routine)]
    for group in (*(g for g in STATED_GROUPS if g < len(people)), len(people)):
        plans.append(
            (
                group,
                RunPlan(
                    run_id=run_id(str(group)),
                    decider=_MODEL,
                    provider_config=_config(),
                    group=None if group == len(people) else frozenset(people[:group]),
                    **base,
                ),
            )
        )
    return plans


def point(graph: dict[str, Any], plan: RunPlan, decided: int, repeats: int) -> dict[str, Any]:
    """One run, played once and read ``repeats`` times as the route reads it."""
    played, play_wall_us, play_cpu_us = _microseconds(lambda: play(plan, _Acting()))
    stored = list(zip(played.requests, played.receipts, strict=True))
    acts: dict[str, int] = {}
    for event in played.events:
        if event.kind in ("said", "picked_up", "put_down", "gave", "took", "hands_missed"):
            acts[event.kind] = acts.get(event.kind, 0) + 1
    people = len(played.start["inhabitants"])
    outcome = {
        "status": "completed",
        "minutes": {"state_sha256": played.minute_digests},
        "events_sha256": played.events_sha256,
        "receipts": {"count": len(played.receipts), "sha256": played.receipts_sha256},
    }
    stored_bytes = sum(
        len(canonical_json(request)) + len(canonical_json(receipt)) for request, receipt in stored
    )
    del played

    def read() -> tuple[bytes, dict[str, Any]]:
        again = verified_replay(plan, stored, outcome)
        document = replay_document(
            plan, {}, "model_a", "0" * 64, again, model_name=lambda model_id: model_id
        )
        return JSONResponse(content=jsonable_encoder(document)).body, document

    walls, cpus = [], []
    body, document = b"", {}
    for _ in range(repeats):
        (body, document), wall_us, cpu_us = _microseconds(read)
        walls.append(wall_us)
        cpus.append(cpu_us)
    drawing = encode(document)
    stored_walls = []
    for _ in range(repeats):
        _served, wall_us, _cpu_us = _microseconds(
            lambda: (
                JSONResponse(
                    content=jsonable_encoder(with_names(decode(drawing), lambda model_id: model_id))
                ).body
            )
        )
        stored_walls.append(wall_us)
    return {
        "graph": graph["key"],
        # The people a run reads: the stated population and the scene's placed beings.
        "population": people,
        "stated_population": plan.population,
        "decided": decided,
        "receipts": len(stored),
        "acts": dict(sorted(acts.items())),
        "stored_request_receipt_bytes": stored_bytes,
        "play_wall_us": play_wall_us,
        "play_cpu_us": play_cpu_us,
        "read_wall_us": _spread(walls),
        "read_cpu_us": _spread(cpus),
        "body_bytes": len(body),
        "drawing_bytes": drawing.document_bytes,
        "drawing_gzip_bytes": len(drawing.document_gzip),
        "stored_read_wall_us": _spread(stored_walls),
    }


def _derived(line: dict[str, Any], populations: list[int]) -> dict[str, Any]:
    """The most people a society of things' comparison runs and the most a model may decide for,
    from the fitted line and the protocol's pair budget, as the reading bound derives them."""
    budget_ms = protocol_value(
        comparison_catalogs_for_engine(THINGS_PROFILE), "pair_replay_budget_ms"
    )
    bound = ReadingBound(
        run_us=budget_ms * 1000 // PAIR_RUNS,
        fixed_us=line["replay_fixed_ms"] * 1000,
        per_person_us=line["replay_per_person_us"],
        per_decided_us=line["replay_per_decided_person_us"],
        per_pair_us=line["replay_per_decided_pair_us"],
    )
    return {
        "pair_replay_budget_ms": budget_ms,
        "run_budget_us": bound.run_us,
        "population_most": bound.population_most(),
        "decided_most": [
            {
                "population": population,
                "decided_most": bound.decided_most(population),
                "estimate_everybody_us": bound.estimate_us(population, population),
            }
            for population in sorted(set(populations))
        ],
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def design() -> dict[str, Any]:
    """Every choice the measurement makes, fixed by the pre-registration before any timed read."""
    return {
        "engine": THINGS_PROFILE,
        "contract": CONTRACT.binding(),
        "square_scene": list(SQUARE_SCENE),
        "town_scene": list(TOWN_SCENE),
        "town": {"preset": TOWN_PRESET, "world_id": TOWN_WORLD_ID},
        "holdables": {
            "count": HOLDABLES,
            "kinds": [list(kind) for kind in HOLDABLE_KINDS],
            "square_grid_mm": {"x": list(SQUARE_GRID_X_MM), "z": list(SQUARE_GRID_Z_MM)},
            "town_apart_mm": TOWN_APART_MM,
        },
        "square_populations": list(SQUARE_POPULATIONS),
        "town_populations_below_own": list(TOWN_POPULATIONS),
        "stated_groups": list(STATED_GROUPS),
        "society_bound_not_measured": SOCIETY_BOUND,
        "answers": {
            "hands_first": list(HANDS_FIRST),
            "saying": list(SAYING),
            "order": "hands first where the request's digest is even, saying first where odd",
            "lines": list(LINES),
            "otherwise": "the option the request's document digest chooses",
        },
        "seed": _SEED,
        "gate": {
            "idle_percent_before_least": str(IDLE_BEFORE_PERCENT),
            "idle_percent_mean_least": str(IDLE_MEAN_PERCENT),
            "load_most_before_each_point": str(LOAD_MOST),
        },
        "line": "least-margin bounding line over every point's 95th percentile read, with its "
        "population-times-decided term (scripts/measure_living_comparison_replay.py's fit)",
    }


def _bound_files() -> dict[str, Any]:
    return {
        "script_sha256": _sha256((ROOT / SCRIPT).read_bytes()),
        "reads": {path: _sha256((ROOT / path).read_bytes()) for path in READS},
    }


def _wrap(record: dict[str, Any]) -> str:
    _refuse_machine_paths(canonical_json(record).decode())
    wrapped = {
        "profile": PROFILE,
        "record_sha256": _sha256(canonical_json(record)),
        "record": record,
    }
    return json.dumps(wrapped, indent=1, sort_keys=True) + "\n"


def preregister(out: Path) -> int:
    if out.exists():
        raise SystemExit(f"refused: {out} exists")
    source = _source()
    if source["changed_paths"]:
        raise SystemExit("refused: the tree is not clean")
    record = {
        "kind": PREREGISTRATION_KIND,
        "source": source,
        "script": SCRIPT,
        **_bound_files(),
        "design": design(),
        "stops": [
            "A graph that does not compose with every thing usable, or a run whose replay differs "
            "from what it recorded, stops the measurement.",
            "A gate refusal is retried only inside the declared window; a discarded record is "
            "not bound.",
        ],
    }
    out.write_text(_wrap(record), encoding="utf-8")
    print(json.dumps({"preregistration": str(out), "script_sha256": record["script_sha256"]}))
    return 0


def _registered(path: Path) -> dict[str, Any]:
    """The pre-registration this run is held to, refused where this script, its reads, the tree
    or the design differ from what it bound."""
    wrapped = json.loads(path.read_text(encoding="utf-8"))
    record = wrapped["record"]
    if wrapped.get("profile") != PROFILE or _sha256(canonical_json(record)) != wrapped.get(
        "record_sha256"
    ):
        raise SystemExit("refused: the pre-registration is not a digest-bound record")
    source = _source()
    if record.get("kind") != PREREGISTRATION_KIND:
        raise SystemExit("refused: not this measurement's pre-registration")
    if record["source"]["head"] != source["head"] or source["changed_paths"]:
        raise SystemExit("refused: the tree is not the registered one, or not clean")
    if record["source"]["drawing_code_sha256"] != CODE_SHA256:
        raise SystemExit("refused: the drawing digest is not the registered one")
    bound = _bound_files()
    if (record["script_sha256"], record["reads"]) != (bound["script_sha256"], bound["reads"]):
        raise SystemExit("refused: the script or a file it reads differs from the registered one")
    if record["design"] != json.loads(canonical_json(design())):
        raise SystemExit("refused: the design differs from the registered one")
    return wrapped


def run(registration: Path, repeats: int, out: Path) -> int:
    if out.exists():
        raise SystemExit(f"refused: {out} exists")
    registered = _registered(registration)
    source = _source()
    idle_before, load_before = idle_share(), load_average()
    if idle_before is not None and idle_before < IDLE_BEFORE_PERCENT:
        print(f"refused: the machine is {idle_before}% idle, under {IDLE_BEFORE_PERCENT}%")
        return 3
    window = protocol_value(comparison_catalogs_for_engine(THINGS_PROFILE), "window_ticks")
    graphs = [compose_square(), compose_town()]
    points = []
    for graph in graphs:
        for population in graph["populations"]:
            for decided, plan in _plans(graph, population, window):
                load = settled()
                found = point(graph, plan, decided, repeats)
                found["load_1m"] = {
                    "before": str(load),
                    "after": str(round(os.getloadavg()[0], 2)),
                }
                points.append(found)
                print(
                    json.dumps(
                        {
                            key: found[key]
                            for key in (
                                "graph",
                                "population",
                                "decided",
                                "receipts",
                                "acts",
                                "read_wall_us",
                                "load_1m",
                            )
                        }
                    ),
                    flush=True,
                )
    idle_after, load_after = idle_share(), load_average()
    mean_idle = (
        None
        if idle_before is None or idle_after is None
        else (Decimal(str(idle_before)) + Decimal(str(idle_after))) / 2
    )
    line = _fit(points, pairs=True)
    record = {
        "kind": KIND,
        "engine": THINGS_PROFILE,
        "source": source,
        "script": SCRIPT,
        **_bound_files(),
        "preregistration_sha256": registered["record_sha256"],
        "window_ticks": window,
        "repeats": repeats,
        "machine": {
            "system": platform.platform(),
            "python": sys.version.split()[0],
            "cpus": os.cpu_count(),
        },
        "gate": {
            "idle_percent_before": _percent(idle_before),
            "idle_percent_after": _percent(idle_after),
            "idle_percent_before_least": str(IDLE_BEFORE_PERCENT),
            "idle_percent_mean_least": str(IDLE_MEAN_PERCENT),
            "load_most_before_each_point": str(LOAD_MOST),
            "load_before": load_before,
            "load_after": load_after,
        },
        "discard": mean_idle is not None and mean_idle < Decimal(str(IDLE_MEAN_PERCENT)),
        "graphs": [{k: v for k, v in graph.items() if k != "document"} for graph in graphs],
        "points": points,
        "line": line,
        "line_without_pairs": _fit(points, pairs=False),
        "largest_population_measured": max(item["population"] for item in points),
        "derived": _derived(line, [item["population"] for item in points] + [SOCIETY_BOUND]),
        "limits": [
            "Scripted answers the engine applies: the most receipts, lines and hands acts a run "
            "holds, not any model's behaviour.",
            "One simulated hour per run; a day is not measured.",
            f"No point measures the society bound of {SOCIETY_BOUND}; what the line implies "
            "beyond the largest population measured is inferred.",
        ],
    }
    out.write_text(_wrap(record), encoding="utf-8")
    print(json.dumps({"line": line, "discard": record["discard"]}))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    steps = parser.add_subparsers(dest="step", required=True)
    pre = steps.add_parser("preregister")
    pre.add_argument("--out", type=Path, required=True)
    measured = steps.add_parser("run")
    measured.add_argument("--preregistration", type=Path, required=True)
    measured.add_argument("--repeats", type=int, default=5)
    measured.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.step == "preregister":
        return preregister(args.out)
    return run(args.preregistration, args.repeats, args.out)


if __name__ == "__main__":
    sys.exit(main())
