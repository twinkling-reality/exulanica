#!/usr/bin/env python3
"""Record the v4 living society over the committed Flatiron district, for the offline preview.

The recording is produced by the actual composition adapter, place projection and v4 engine. No
database, network, personal material or rights assertion is involved, and no frame is authored:
every frame carries the digest of the canonical state it presents, and ``verify_recording``
replays the engine to prove it. Frames keep only what the preview draws and inspects.

Usage: ``uv run python -m scripts.record_living_society --ticks 180 --output recording.json``.
With no ``--output`` the recording is written to standard output, which is how the web
preview's development server reads it.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Final

from exulanica.environment.district_geometry import DistrictGeometry, segment_blocked
from exulanica.environment.district_interpretation import validate_interpretation
from exulanica.world.objects import AlternateVersion, delta_sha256
from exulanica.world.society import society_state_sha256
from exulanica.world.society_catalogs import load_routine_model
from exulanica.world.society_composition import build_society_input
from exulanica.world.society_living import (
    LIVING_PROFILE,
    LivingPlace,
    advance_living_society,
    initial_living_society,
)
from exulanica.world.society_place import place_from_society_input

ROOT: Final = Path(__file__).resolve().parents[1]
FLATIRON_BASE: Final = ROOT / "assets/owned-world/flatiron/flatiron-owned-district.json"
FLATIRON_INTERPRETATION: Final = (
    ROOT / "assets/owned-world/flatiron-interpretation-v1/district-interpretation.json"
)
PROFILE: Final = "exulanica.living-society-recording/v1"
VERSION_ID: Final = uuid.UUID("5d2b8f61-3c4e-5a70-9b1d-7e6f0a2c4b17")
SNAPSHOT_ID: Final = uuid.uuid5(VERSION_ID, "fictional-living-society-source-snapshot")
ACTOR_ID: Final = uuid.uuid5(VERSION_ID, "fictional-living-society-author")
SOCIETY_ID: Final = uuid.uuid5(VERSION_ID, "exulanica-society/v1")
REGION_ID: Final = "preview-flatiron-local"
SEED: Final = "6b" * 32
FIXTURE_TIME: Final = "2026-09-16T00:00:00Z"
DEFAULT_TICKS: Final = 180


def flatiron_input(interpretation_path: Path = FLATIRON_INTERPRETATION) -> dict[str, Any]:
    """Compose the unedited Flatiron society input exactly as the runtime adapter would."""
    base = FLATIRON_BASE.read_bytes()
    district = validate_interpretation(interpretation_path.read_bytes(), base).model_dump(
        mode="json"
    )
    version = AlternateVersion(
        version_id=VERSION_ID,
        world_id="atlas:default",
        source_snapshot_id=SNAPSHOT_ID,
        parent_version_id=None,
        title="Fictional living society preview",
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
    dependencies = [
        {"kind": "fixture_source", "identity": dep["dataset_id"], "sha256": dep["sha256"]}
        for dep in district["source_dependencies"]
    ]
    document = build_society_input(
        interpretation=district,
        base_bytes=base,
        version=version,
        registration=registration,
        input_seq=1,
        dependency_refs=sorted(dependencies, key=lambda d: (d["kind"], d["identity"])),
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        supports=DistrictGeometry(json.loads(base)).supports,
        segment_blocked=segment_blocked,
    )
    if document["availability"] != "available":
        raise ValueError(f"Flatiron composition unavailable: {document['unavailable_reason']}")
    return document


def _roster(state: dict[str, Any]) -> list[dict[str, Any]]:
    """What never changes about an inhabitant, stated once; frames list people in this order."""
    return [
        {
            "id": person["id"],
            "synthetic": True,
            "role": person["role"]["label"] if person["role"] else None,
            "role_reason": person["role_reason"],
            "walk_speed_mm_per_tick": person["walk_speed_mm_per_tick"],
        }
        for person in state["inhabitants"]
    ]


def _inhabitant(person: dict[str, Any]) -> dict[str, Any]:
    goal = person["goal"]
    return {
        "position_mm": person["position_mm"],
        "motion_path_mm": person["motion_path_mm"],
        "indoors": person["location"]["indoors"],
        "action": {
            key: person["action"][key] for key in ("kind", "status", "destination_id", "reason")
        },
        "goal": None
        if goal is None
        else {key: goal[key] for key in ("activity", "destination_id", "because")},
        "needs": person["needs"],
        "explanation_event_ids": person["explanation"]["event_ids"],
    }


def _frame(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "tick": state["tick"],
        "minute_of_day": state["clock"]["minute_of_day"],
        "day": state["clock"]["day"],
        "state_sha256": society_state_sha256(state),
        "inhabitants": [_inhabitant(p) for p in state["inhabitants"]],
    }


def record(ticks: int = DEFAULT_TICKS, seed: str = SEED) -> dict[str, Any]:
    if type(ticks) is not int or not 1 <= ticks <= 1440:
        raise ValueError("a recording spans 1 to 1440 simulated minutes")
    routine = load_routine_model()
    document = flatiron_input()
    place_document = place_from_society_input(document, routine)
    place = LivingPlace(place_document, routine)
    state = initial_living_society(
        SOCIETY_ID, seed, place, routine, branch_id=document["version_id"]
    )
    roster = _roster(state)
    frames = [_frame(state)]
    events = []
    for _ in range(ticks):
        state, produced = advance_living_society(state, seed, [place], routine)
        frames.append(_frame(state))
        events.extend(
            {
                "event_id": str(event.event_id),
                "subject_id": str(event.subject_id),
                "tick": event.tick,
                "kind": event.kind,
                "summary": event.document["summary"],
                "destination_id": (event.document["goal"] or {}).get("destination_id"),
            }
            for event in produced
        )
    return {
        "profile": PROFILE,
        "status": (
            "Recorded by the v4 living society engine over the committed Flatiron district input. "
            "Fictional inhabitants; no database persistence, personal material or live rights "
            "assertion."
        ),
        "engine_profile": LIVING_PROFILE,
        "generator": {"script": "scripts/record_living_society.py", "seed": seed, "ticks": ticks},
        "society_id": state["society_id"],
        "branch_id": state["branch_id"],
        "district_id": document["district_id"],
        "district_document_sha256": document["district_document_sha256"],
        "input_sha256": document["document_sha256"],
        "routine": state["routine"],
        "population": state["population"],
        "place": {
            "place_sha256": place_document["document_sha256"],
            "capacity": state["place"]["capacity"],
            "spots": len(place_document["spots"]),
            "nodes": len(place_document["nodes"]),
            "destinations": [
                {
                    "destination_id": d["destination_id"],
                    "subject_id": d["subject_id"],
                    "affordances": d["affordances"],
                    "visitor_capacity": d["visitor_capacity"],
                }
                for d in place_document["destinations"]
            ],
            "unsupported": place_document["unsupported"],
        },
        "environment": state["environment"],
        "roster": roster,
        "frames": frames,
        "events": events,
    }


def verify_recording(recording: dict[str, Any]) -> None:
    """Replay the engine from genesis and require every frame to present that exact state."""
    generator = recording["generator"]
    replayed = record(generator["ticks"], generator["seed"])
    for held, fresh in zip(recording["frames"], replayed["frames"], strict=True):
        if held != fresh:
            raise ValueError(f"recorded frame {held['tick']} does not match the engine")
    if recording["events"] != replayed["events"]:
        raise ValueError("recorded events do not match the engine")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=DEFAULT_TICKS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    payload = json.dumps(record(args.ticks), separators=(",", ":"))
    if args.output is None:
        sys.stdout.write(payload)
    else:
        args.output.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
