"""Start a scene's society on a saved world as a person left it, and record the world for a rehearsal.

    EXULANICA_TOKEN=<token> python3 scripts/demo/start_society.py <scene document> \
        --base-url http://127.0.0.1:<api port> --record <record.json> [--entry <entry id>]

A person can place a scene's things themselves, through the Companion from one sentence: the things
then carry the ids the Companion minted and stand where its layout put them. This script starts the
society of things they live in, and places nothing and chooses no mind. It reads the saved world
(``--entry``, or the workspace's only saved world) and its version as they stand, and starts the
society the scene document's engine names on that version, in the arrival's region
(``POST /world/versions/{version}/society``; asked again, the version's society is read back). The
person then chooses each being's mind in Who decides, as the world's owner does; running this again
records the minds they chose.

The scene document lends what the sentence does not state: the society's engine, the scene's title
and digest, and the travellers its gate lets in with the mind the world gives them. The gate they
come through is the version's one placed thing of the kind the scene's own gate is; a world holding
none or several of that kind is refused by name.

The record carries the fields a rehearsal's later steps read from the builder's record
(``build_scene.py``): the scene's digest, the world, saved entry and version with its state digest
and edit count, the arrival's region, every placed thing as the version stores it, the travellers
with the world's own gate, and the society with each placed being's person id beside its placed id
and the mind read back for it (none: the routine). ``placed_by`` says a person placed the things.
It never holds the token or anything the token grants.

Standard library only; it shares the builder's client and readers rather than copying them.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

RECORD_PROFILE = "exulanica.demo-scene-as-placed/v1"
#: Who placed the world's things, as the record says it: not the builder.
PLACED_BY = "person"


def _scene_builder() -> Any:
    """The scene builder beside this script (its API client, readers and digest), loaded once."""
    loaded = sys.modules.get("build_scene")
    if loaded is not None:
        return loaded
    spec = importlib.util.spec_from_file_location(
        "build_scene", Path(__file__).with_name("build_scene.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_scene"] = module
    spec.loader.exec_module(module)
    return module


builder = _scene_builder()
SceneRefused = builder.SceneRefused


def saved_world(api: Any, entry_id: str | None) -> Mapping[str, Any]:
    """The saved world ``entry_id`` names, or the workspace's only one."""
    if entry_id is not None:
        return api.call("GET", f"/world-entries/{entry_id}")
    entries = api.call("GET", "/world-entries")
    if len(entries) != 1:
        raise SceneRefused(
            f"the workspace holds {len(entries)} saved worlds: name one with --entry"
        )
    return entries[0]


def gate_of(scene: Mapping[str, Any], things: Sequence[Mapping[str, Any]]) -> str | None:
    """The placed thing travellers come through: the world's one thing of the scene gate's kind,
    or None when the scene lets no travellers in."""
    gate = scene.get("travellers", {}).get("gate")
    if gate is None:
        return None
    kind = next(thing["kind"]["kind"] for thing in scene["things"] if thing["thing_id"] == gate)
    gates = [thing["thing_id"] for thing in things if thing["kind"]["kind"] == kind]
    if len(gates) != 1:
        raise SceneRefused(
            f"travellers come through a {kind}, and the world holds {len(gates)} of them"
        )
    return gates[0]


def _model(stored: Mapping[str, Any] | None) -> dict[str, str] | None:
    return None if stored is None else {k: stored[k] for k in ("provider", "model_id")}


def start(api: Any, scene: Mapping[str, Any], entry_id: str | None = None) -> dict[str, Any]:
    """Start the scene's society on the saved world as it stands, and return its record."""
    engine = scene.get("engine")
    if engine is None:
        raise SceneRefused("the scene names no engine for its society")
    entry = saved_world(api, entry_id)
    world_id, version_id = entry["world_id"], entry["authored_version_id"]
    arrival = builder.arrival_of(entry)
    version = api.call("GET", f"/world/versions/{version_id}", world_id=world_id)
    things = [thing for thing in version.get("things", []) if not thing["removed"]]
    gate = gate_of(scene, things)
    society_path = f"/world/versions/{version_id}/society"
    society = api.call(
        "POST",
        society_path,
        {"region_id": arrival.region_id, "profile": engine},
        world_id=world_id,
    )
    if society["profile"] != engine:
        raise SceneRefused(f"the version's society runs {society['profile']}, not {engine}")
    view = api.call("GET", f"{society_path}/models", world_id=world_id)
    held = {choice["subject_id"]: choice["model"] for choice in view["choices"]}
    record = {
        "profile": RECORD_PROFILE,
        "scene": {
            "scene": scene["scene"],
            "version": scene["version"],
            "sha256": builder._digest(scene),
        },
        "started_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "placed_by": PLACED_BY,
        "world_id": world_id,
        "arrival": {
            "region_id": arrival.region_id,
            "at_mm": list(arrival.at_mm),
            "facing": list(arrival.facing),
        },
        "entry_id": entry["entry_id"],
        "version_id": version_id,
        "state_sha256": version["state_sha256"],
        "edit_seq": version["edit_seq"],
        "things": [
            {
                "thing_id": thing["thing_id"],
                "kind": thing["kind"],
                "region_id": thing["region_id"],
                "pose": builder._stored_pose(thing),
            }
            for thing in things
        ],
        "engine": engine,
        "society": {
            "society_id": society["society_id"],
            "engine": society["profile"],
            "state_sha256": society["state_sha256"],
            # Why no model would be asked here (no key, no allowance), as the server says.
            "host_refusal": view.get("host_refusal"),
            "minds": [
                {
                    "thing_id": person["placed_id"],
                    "person_id": person["id"],
                    "model": _model(held.get(person["id"])),
                }
                for person in society["state"]["inhabitants"]
                if person.get("came_by") == "placed"
            ],
        },
    }
    if gate is not None:
        record["travellers"] = {**scene["travellers"], "gate": gate}
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("scene", type=Path, help="the scene document lending engine and travellers")
    parser.add_argument("--base-url", required=True, help="the API's address")
    parser.add_argument("--record", type=Path, required=True, help="where to write the record")
    parser.add_argument("--entry", help="the saved world; the workspace's only one without it")
    args = parser.parse_args(argv)
    token = os.environ.get("EXULANICA_TOKEN")
    if not token:
        print("set EXULANICA_TOKEN to a token with world.read and world.write", file=sys.stderr)
        return 2
    try:
        api = builder.Api(args.base_url, token)
        record = start(api, builder.read_scene(args.scene), args.entry)
    except SceneRefused as refused:
        print(f"not started: {refused}", file=sys.stderr)
        return 1
    args.record.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    society = record["society"]
    minds = ", ".join(
        f"{mind['thing_id']} {(mind['model'] or {}).get('model_id', 'routine')}"
        for mind in society["minds"]
    )
    print(
        f"society {society['society_id']} on {society['engine']} over "
        f"{len(record['things'])} placed things, version {record['version_id']}: {minds}"
    )
    if society["host_refusal"]:
        print(f"no model is asked here yet: {society['host_refusal']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
