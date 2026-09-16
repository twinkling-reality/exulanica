#!/usr/bin/env python3
"""Generate an offline fictional society preview from the validated owned district.

No database, network, current rights assertion or personal material is involved. The output is
an inspectable recording of the actual pure composition/planner code, not authored animations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, replace
from itertools import pairwise
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.env import resolve_briefs_path
from exulanica.environment.district_geometry import DistrictGeometry
from exulanica.environment.district_geometry import segment_blocked
from exulanica.environment.district_interpretation import (
    compile_interpretation,
    validate_interpretation,
)
from exulanica.world.assets import reviewed_assets
from exulanica.world.objects import (
    AlternateVersion,
    AuthoredObject,
    ObjectOrigin,
    Transform,
    delta_sha256,
    object_document,
)
from exulanica.world.society import SOCIETY_POPULATION, society_state_sha256
from exulanica.world.society_composition import build_society_input
from exulanica.world.society_planner import (
    initial_purposeful_society,
    advance_purposeful_society,
    ordered_events_document,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / "assets/owned-world/flatiron/flatiron-owned-district.json"
DEFAULT_OUTPUT = resolve_briefs_path("living-world-preview.generated.json", root=ROOT)
PROFILE = "exulanica.living-world-preview-fixture/v1"
GENERATOR_PROFILE = "exulanica.living-world-preview-generator/v1"
VERSION_ID = uuid.UUID("0d8a86be-37a0-5bdb-b300-85f2f4b20740")
SOCIETY_ID = uuid.uuid5(VERSION_ID, "exulanica-society/v1")
PLACE_ID = uuid.UUID("d08f61bb-ef6d-4f5d-8bd8-a596da51f971")
SNAPSHOT_ID = uuid.uuid5(VERSION_ID, "fictional-preview-source-snapshot")
ACTOR_ID = uuid.uuid5(VERSION_ID, "fictional-preview-author")
SEED = "7a" * 32
REGION_ID = "preview-flatiron-local"
FIXTURE_TIME = "2026-09-13T00:00:00Z"


@dataclass(frozen=True)
class PreviewScenario:
    """Authored fixture inputs, never per-inhabitant instructions or state patches."""

    asset_key: str = "cc0.marker-cube"
    object_id: str = "object:preview-visit-marker"
    node_id: str = "nyc-flatiron-owned-v1/walk:32000:76000"
    offset_mm: tuple[int, int] = (0, -1000)
    edit_ticks: tuple[int, int, int] = (5, 10, 13)
    final_tick: int = 18

    def __post_init__(self) -> None:
        if (
            type(self.final_tick) is not int
            or len(self.edit_ticks) != 3
            or any(type(t) is not int for t in self.edit_ticks)
            or not 0
            < self.edit_ticks[0]
            < self.edit_ticks[1]
            < self.edit_ticks[2]
            < self.final_tick
            or self.final_tick > 100
            or len(self.offset_mm) != 2
            or any(type(n) is not int for n in self.offset_mm)
        ):
            raise ValueError("invalid bounded preview scenario")


def _registry() -> dict[str, dict[str, Any]]:
    """Explicit fixture assignments for the existing CC0 catalog, not live grants."""
    declarations = {
        "cc0.marker-cube": ("visit", 1, [250, 250], True),
        "cc0.marker-pillar": ("visit", 1, [125, 125], True),
        "cc0.marker-plate": ("rest", 3, [500, 500], False),
    }
    return {
        asset.content_sha256: {
            "asset_key": asset.asset_key,
            "affordance": declarations[asset.asset_key][0],
            "duration_ticks": declarations[asset.asset_key][1],
            "footprint_half_extents_mm": declarations[asset.asset_key][2],
            "blocks_navigation": declarations[asset.asset_key][3],
            "reach_mm": 6000,
        }
        for asset in reviewed_assets()
    }


def _snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": state["profile"],
        "society_id": state["society_id"],
        "world_id": "atlas:default",
        "version_id": str(VERSION_ID),
        "place_id": str(PLACE_ID),
        "region_id": REGION_ID,
        "seed": SEED,
        "population_size": SOCIETY_POPULATION,
        "tick_seconds": state["tick_seconds"],
        "current_tick": state["tick"],
        "state": state,
        "state_sha256": society_state_sha256(state),
        "created_by": str(ACTOR_ID),
        "created_at": FIXTURE_TIME,
        "branch_id": state["branch_id"],
        "input_seq": state["input_seq"],
        "input_sha256": state["input_sha256"],
    }


def assert_supported_motion(state: dict[str, Any], geometry: DistrictGeometry) -> None:
    """Check all recorded segments, including bends/mid-edge endpoints, never endpoint shortcuts."""
    if len(state["inhabitants"]) != SOCIETY_POPULATION:
        raise ValueError("preview population was truncated")
    for person in state["inhabitants"]:
        path = person["motion_path_mm"]
        if not path or path[-1] != person["position_mm"]:
            raise ValueError("invalid recorded motion path")
        pairs = list(pairwise(path)) if len(path) > 1 else [(path[0], path[0])]
        for start, end in pairs:
            if not geometry.supports(tuple(start), tuple(end), 450):
                raise ValueError(f"unsupported recorded segment at tick {state['tick']}")


def generate_preview(
    base_bytes: bytes,
    interpretation_bytes: bytes | None = None,
    *,
    pad_node_id: str | None = None,
    scenario: PreviewScenario | None = None,
    with_edits: bool = True,
) -> dict[str, Any]:
    """Return deterministic frames from declared fixture edits, or their no-edit control.

    The default pad location is an explicit authored fixture choice, not inferred geography.
    A different source/graph can supply its exact existing access node through pad_node_id.
    """
    parsed = validate_interpretation(
        compile_interpretation(base_bytes)
        if interpretation_bytes is None
        else interpretation_bytes,
        base_bytes,
    )
    district = parsed.model_dump(mode="json")
    geometry = DistrictGeometry(json.loads(base_bytes))
    selected_id = pad_node_id or (
        scenario.node_id if scenario else f"{district['district_id']}/walk:48000:132000"
    )
    nodes = {node["node_id"]: node for node in district["navigation"]["nodes"]}
    if selected_id not in nodes:
        raise ValueError(
            "fixture pad node is absent; supply --pad-node-id with an exact validated node"
        )
    px, pz = nodes[selected_id]["position_mm"]
    registry = _registry()
    asset_key = scenario.asset_key if scenario else "cc0.marker-plate"
    matches = [digest for digest, row in registry.items() if row["asset_key"] == asset_key]
    if not matches:
        raise ValueError("scenario asset is not in the reviewed fixture registry")
    plate_digest = matches[0]
    if scenario:
        px += scenario.offset_mm[0]
        pz += scenario.offset_mm[1]
    plate = AuthoredObject(
        scenario.object_id if scenario else "object:preview-rest-pad",
        plate_digest,
        REGION_ID,
        Transform(px, 0, pz, 0, 1000),
        ObjectOrigin("authored", "fictional"),
    )
    version = AlternateVersion(
        version_id=VERSION_ID,
        world_id="atlas:default",
        source_snapshot_id=SNAPSHOT_ID,
        parent_version_id=None,
        title="Fictional living-world preview",
        style_version_id=None,
        state_sha256=delta_sha256((), ()),
        edit_seq=0,
        source_invalidated=False,
        created_by=ACTOR_ID,
        created_at=FIXTURE_TIME,
    )
    registration = {
        "world_id": version.world_id,
        "version_id": str(VERSION_ID),
        "source_snapshot_id": str(SNAPSHOT_ID),
        "region_id": REGION_ID,
        "district_id": district["district_id"],
        "frame_name": district["frame"]["name"],
        "translation_mm": [0, 0, 0],
        "yaw_microradians": 0,
        "scale_milli": 1000,
    }
    fixture_settings = {
        "profile": GENERATOR_PROFILE,
        "pad_node_id": selected_id,
        "seed": SEED,
        "version_id": str(VERSION_ID),
        "changes_at_ticks": [5, 9, 13],
    }
    edit_ticks = scenario.edit_ticks if scenario else (5, 9, 13)
    final_tick = scenario.final_tick if scenario else 18
    if scenario:
        fixture_settings.update(
            profile="exulanica.living-world-preview-generator/v2",
            changes_at_ticks=list(edit_ticks),
            final_tick=final_tick,
            authored_object=object_document(plate),
        )
    dependencies = [
        {"kind": "fixture_source", "identity": dep["dataset_id"], "sha256": dep["sha256"]}
        for dep in district["source_dependencies"]
    ] + [
        {
            "kind": "fixture_generator",
            "identity": fixture_settings["profile"],
            "sha256": society_state_sha256(fixture_settings),
        }
    ]

    def composed(input_seq: int) -> dict[str, Any]:
        document = build_society_input(
            interpretation=district,
            base_bytes=base_bytes,
            version=version,
            registration=registration,
            input_seq=input_seq,
            dependency_refs=dependencies,
            availability="available",
            unavailable_reason=None,
            reviewed_affordances=registry,
            supports=geometry.supports,
            segment_blocked=segment_blocked,
        )
        if document["availability"] != "available":
            raise ValueError(f"preview composition unavailable: {document['unavailable_reason']}")
        return document

    inputs = [composed(1)]
    state = initial_purposeful_society(SOCIETY_ID, SEED, inputs[0])
    initial_occupancy = Counter(tuple(person["position_mm"]) for person in state["inhabitants"])
    frames = []
    event_documents = []
    label = "affordance" if scenario else "rest_pad"
    changes = (
        dict(
            zip(
                edit_ticks,
                [f"add_fixture_{label}", f"disable_fixture_{label}", f"restore_fixture_{label}"],
                strict=True,
            )
        )
        if with_edits
        else {}
    )
    for tick in range(final_tick + 1):
        change = changes.get(tick)
        previous_input = inputs[-1]
        if change is not None:
            objects = (replace(plate, removed=tick == edit_ticks[1]),)
            version = replace(
                version,
                objects=objects,
                edit_seq=version.edit_seq + 1,
                state_sha256=delta_sha256(objects, ()),
            )
            inputs.append(composed(len(inputs) + 1))
        if tick > 0:
            step_inputs = [previous_input] if change is None else [previous_input, inputs[-1]]
            state, events = advance_purposeful_society(state, SEED, step_inputs)
            event_documents.extend(ordered_events_document(events))
        assert_supported_motion(state, geometry)
        frames.append(
            {
                "change": change,
                "authored_objects": [
                    object_document(obj) for obj in version.objects if not obj.removed
                ],
                "snapshot": _snapshot(state),
            }
        )
    pad_events = [
        event
        for event in event_documents
        if (event["document"].get("target") or {}).get("object_id") == plate.object_id
    ]
    subject_label = "authored affordance" if scenario else "rest pad"
    pad_effect = (
        f"No recorded inhabitant goal or action targets the {subject_label} in this window; "
        f"the recording demonstrates input changes only, not a behavioral response to the {'affordance' if scenario else 'pad'}. "
        if not pad_events
        else f"{len(pad_events)} recorded events target the {subject_label}; inspect their outcomes for evidence. "
    )
    if not with_edits:
        pad_effect = "No authored edits were applied in this same-seed counterfactual. "
    return {
        "profile": PROFILE,
        "district_document_sha256": district["document_sha256"],
        "frame_binding": {
            "kind": "authored_fixture_identity",
            "region_id": REGION_ID,
            "frame": district["frame"],
            "translation_mm": [0, 0, 0],
            "yaw_microradians": 0,
            "scale_milli": 1000,
        },
        "frames": frames,
        "inputs": inputs,
        "events": event_documents,
        "status": (
            "Generated fictional preview mechanics on the validated A district graph; "
            "no database persistence, personal material or live rights assertion. "
            "Authored changes are labeled fixture inputs, not user edits. "
            + pad_effect
            + f"Initial population spans {len(initial_occupancy)} declared nodes, "
            f"at most {max(initial_occupancy.values())} inhabitants per node. "
            "Later destination co-location is canonical: this policy has no crowd or capacity model."
        ),
    }


def verify_preview(recording: dict[str, Any], base_bytes: bytes) -> None:
    """Replay persisted JSON receipts; no current geometry substitutes for historical inputs."""
    inputs = recording["inputs"]
    first = recording["frames"][0]["snapshot"]
    state = initial_purposeful_society(uuid.UUID(first["society_id"]), first["seed"], inputs[0])
    geometry = DistrictGeometry(json.loads(base_bytes))
    produced_events = []
    for tick, frame in enumerate(recording["frames"]):
        expected = frame["snapshot"]
        if tick:
            state, events = advance_purposeful_society(
                state, first["seed"], inputs[state["input_seq"] - 1 : expected["input_seq"]]
            )
            produced_events.extend(ordered_events_document(events))
        if state != expected["state"] or society_state_sha256(state) != expected["state_sha256"]:
            raise ValueError(f"preview state replay mismatch at tick {tick}")
        assert_supported_motion(state, geometry)
    if produced_events != recording["events"]:
        raise ValueError("preview event replay mismatch")


def generate_causal_preview(
    base_bytes: bytes,
    interpretation_bytes: bytes | None = None,
    *,
    scenario: PreviewScenario | None = None,
) -> dict[str, Any]:
    """Measure edit effects against identical initial state/seed with edits suppressed.

    Both arms bind the same scenario declaration, so the initial input and state are identical.
    No intervention edits state or events, and no scenario mutates the production policy.
    """
    scenario = scenario or PreviewScenario()
    treatment = generate_preview(base_bytes, interpretation_bytes, scenario=scenario)
    control = generate_preview(
        base_bytes, interpretation_bytes, scenario=scenario, with_edits=False
    )
    verify_preview(treatment, base_bytes)
    verify_preview(control, base_bytes)
    add, remove, reopen = scenario.edit_ticks
    if treatment["frames"][:add] != control["frames"][:add]:
        raise ValueError("counterfactual initial history differs")
    target_events = [
        event
        for event in treatment["events"]
        if (event["document"].get("target") or {}).get("object_id") == scenario.object_id
    ]
    first_completions = {
        e["subject_id"]
        for e in target_events
        if add <= e["tick"] < remove and e["event_kind"] == "action_completed"
    }
    interrupted = {
        p["id"]
        for p in treatment["frames"][remove - 1]["snapshot"]["state"]["inhabitants"]
        if (p.get("target") or {}).get("object_id") == scenario.object_id
        and p["action"]["status"] == "active"
    }
    replanned = {
        e["subject_id"]
        for e in target_events
        if e["tick"] == remove
        and e["event_kind"] == "replanned"
        and e["document"]["reason"] == "target_disabled_or_removed"
    }
    reopened_completions = {
        e["subject_id"]
        for e in target_events
        if e["tick"] >= reopen and e["event_kind"] == "action_completed"
    }
    candidates = sorted(first_completions & interrupted & replanned & reopened_completions)
    if not candidates:
        raise ValueError("scenario lacks a witness for use, interrupted action, and restored use")
    if any(
        (e["document"].get("target") or {}).get("object_id") == scenario.object_id
        for e in control["events"]
    ):
        raise ValueError("counterfactual contains an unintroduced affordance")
    if any(
        remove <= e["tick"] < reopen and e["event_kind"] == "action_completed"
        for e in target_events
    ):
        raise ValueError("removed affordance completed an action")
    witness = candidates[0]
    witness_events = [e for e in target_events if e["subject_id"] == witness]
    if not any(len(e["document"]["motion_path_mm"]) > 1 for e in witness_events):
        raise ValueError("witness did not traverse a route to the affordance")
    comparisons = []
    for tick in (add, remove - 1, remove, reopen, scenario.final_tick):
        arms = []
        for recording in (treatment, control):
            person = next(
                p
                for p in recording["frames"][tick]["snapshot"]["state"]["inhabitants"]
                if p["id"] == witness
            )
            arms.append({key: person[key] for key in ("position_mm", "goal", "action", "target")})
        comparisons.append({"tick": tick, "treatment": arms[0], "no_edit": arms[1]})
    if not any(
        row["treatment"]["position_mm"] != row["no_edit"]["position_mm"] for row in comparisons
    ):
        raise ValueError("scenario lacks a spatial counterfactual difference")
    return {
        "profile": "exulanica.living-world-causal-fixture/v1",
        "scenario": asdict(scenario),
        "treatment": treatment,
        "no_edit": control,
        "evidence": {
            "subject_id": witness,
            "object_id": scenario.object_id,
            "same_initial_state_sha256": treatment["frames"][0]["snapshot"]["state_sha256"],
            "witness_events": witness_events,
            "comparisons": comparisons,
            "initial_users": len(first_completions),
            "active_actions_interrupted": len(interrupted & replanned),
            "restored_users": len(reopened_completions),
        },
        "scope": "Pure fictional fixture with actual A geometry and unchanged v2 planner; "
        "not authenticated persistence evidence or a claim of learned social intelligence.",
    }


def write_preview(document: dict[str, Any], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(document) + b"\n"
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=destination.name + ".", delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(payload)
            handle.flush()
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument(
        "--interpretation", type=Path, help="Exact A artifact; otherwise compile locally, offline"
    )
    parser.add_argument(
        "--pad-node-id", help="Exact declared node; default is the labeled Flatiron fixture node"
    )
    parser.add_argument(
        "--causal-proof",
        action="store_true",
        help="Generate matched edited/no-edit visit scenario and measured evidence",
    )
    parser.add_argument(
        "--scenario", type=Path, help="JSON PreviewScenario parameters, for --causal-proof"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    protected = {args.base.resolve()}
    if args.interpretation is not None:
        protected.add(args.interpretation.resolve())
    if args.scenario is not None:
        protected.add(args.scenario.resolve())
        if not args.causal_proof:
            parser.error("--scenario requires --causal-proof")
    if args.output.resolve() in protected:
        parser.error("output must not overwrite an input artifact")
    interpretation = None if args.interpretation is None else args.interpretation.read_bytes()
    if args.causal_proof:
        if args.pad_node_id:
            parser.error("set node_id in --scenario for causal proof")
        scenario = (
            PreviewScenario()
            if args.scenario is None
            else PreviewScenario(**json.loads(args.scenario.read_text()))
        )
        document = generate_causal_preview(
            args.base.read_bytes(), interpretation, scenario=scenario
        )
    else:
        document = generate_preview(
            args.base.read_bytes(), interpretation, pad_node_id=args.pad_node_id
        )
    write_preview(document, args.output)
    print(f"output={args.output.resolve()}")
    print(f"sha256={hashlib.sha256(args.output.read_bytes()).hexdigest()}")
    print("population=128, fictional offline preview only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
