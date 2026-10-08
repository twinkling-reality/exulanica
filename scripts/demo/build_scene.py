"""Build a demo scene in a running Exulanica through its public routes, and record what was built.

    EXULANICA_TOKEN=<token> python3 scripts/demo/build_scene.py scripts/demo/scenes/<scene>.v1.json \
        --base-url http://127.0.0.1:<api port> --record <record.json>

A scene document (``exulanica.scene/v1`` from the scene catalog, ``assets/catalogs/scenes``, or the
demo's earlier ``exulanica.demo-scene/v1``) is data: the things placed by kind, each placed from
where a person arrives in the world (``right_mm`` to their right, ``forward_mm`` ahead, and
``turn_microradians`` counterclockwise seen from above, where a turn of 0 faces the person arriving,
as an object a person places in front of themselves turns to face them, and a turn of pi faces the
way they face),
and the open model chosen as each being's mind. Placing from the arrival lets one document dress any
saved world: a starter, a town made from words, a site made from a world kind. This script names no
scene, kind or thing; it reads the document and makes the same edits a person's browser makes, each
bound to the saved world so the world reopens with them:

1.  ``--entry`` names the saved world to dress; without it, ``POST /world-entries/starter`` makes or
    reuses the workspace's starter world under the scene's title (a starter the app made first,
    under its own title, is refused as a conflict: name that world with ``--entry``);
2.  the world's own arrival point and facing come from its entry (a starter's spawn, a generated
    town's or site's arrival), and each place is turned into the region's frame from them;
3.  ``POST /world/versions/{version}/things`` places each thing by its shipped kind, in the
    document's order, each against the version state the previous edit returned, and a thing
    already placed with the same kind and pose is left as it is, so a second run changes nothing;
4.  the version is read back and every placed thing is checked against the document: kind, version,
    region and pose.

With ``--minds`` it then brings the scene to life as the world's owner would:

5.  ``POST /world/versions/{version}/society`` starts the society the document's engine names on the
    version built, in the arrival's region (asked again, the version's society is read back);
6.  ``POST /world/versions/{version}/society/models`` chooses, for each being the document gives a
    mind, the open model it names (or the routine), keyed by the scene's digest, the society and the
    thing, so a second run asks for the same choices and is answered with the ones recorded; the
    choices are read back from ``GET /world/versions/{version}/society/models``.

The record it writes is the scene's fixture for a rehearsal: the scene document's digest, the world,
saved entry and version it built, the version's state digest and edit count, every placed thing's
kind digest as the server stored it, and with ``--minds`` the society, its engine and each being's
chosen mind. It never holds the token or anything the token grants.

Standard library only, like the developer client, so it shares no code with what it drives.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The profiles a scene document may state: the catalog's, and the demo's earlier one.
SCENE_PROFILES = ("exulanica.scene/v1", "exulanica.demo-scene/v1")
RECORD_PROFILE = "exulanica.demo-scene-build/v1"
TIMEOUT_SECONDS = 30
#: A full turn in microradians, the most a placed thing's yaw states.
FULL_TURN = 6_283_185
#: The namespace of the keys this script chooses minds under: the same scene, society and thing
#: always give the same key, so asking again is answered with the choice already recorded.
MINDS_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "exulanica.demo-scene-build/v1/minds")


def mind_key(scene_sha256: str, society_id: str, thing_id: str) -> uuid.UUID:
    """The key a being's mind is chosen under: the scene's digest, the society and the thing."""
    return uuid.uuid5(MINDS_NAMESPACE, f"{scene_sha256}:{society_id}:{thing_id}")


class SceneRefused(RuntimeError):
    """A scene this script will not build, or a server answer it will not accept."""


def read_scene(path: Path) -> dict[str, Any]:
    scene = json.loads(path.read_text(encoding="utf-8"))
    if scene.get("profile") not in SCENE_PROFILES:
        raise SceneRefused(f"{path} is not a scene document ({', '.join(SCENE_PROFILES)})")
    ids = [thing["thing_id"] for thing in scene["things"]]
    if len(set(ids)) != len(ids):
        raise SceneRefused("each thing is placed once")
    for mind in scene.get("minds", []):
        if mind["thing_id"] not in ids:
            raise SceneRefused(f"a mind is chosen for {mind['thing_id']}, which the scene lacks")
    gate = scene.get("travellers", {}).get("gate")
    if gate is not None and gate not in ids:
        raise SceneRefused(f"travellers come through {gate}, which the scene lacks")
    return scene


def _digest(document: Mapping[str, Any]) -> str:
    """SHA-256 of the document as sorted, compact JSON: the same bytes for the same document."""
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Api:
    """The public API at ``base_url``, asked with one bearer token that is never printed."""

    def __init__(self, base_url: str, token: str) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        loopback = parsed.hostname in ("127.0.0.1", "localhost", "::1")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise SceneRefused("the API is https, or plain http on a loopback address only")
        self._base = base_url.rstrip("/")
        self._token = token

    def call(self, method: str, path: str, body: Any = None, **query: str) -> Any:
        url = self._base + path + (f"?{urllib.parse.urlencode(query)}" if query else "")
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            try:
                problem = json.loads(error.read() or b"{}")
            except json.JSONDecodeError:
                problem = {}
            raise SceneRefused(refusal(method, path, error.code, problem)) from None


def refusal(method: str, path: str, status: int, problem: Any) -> str:
    """A server's refusal in words: its code with the detail the server states beside it, or the
    first thing a request's check refused (where in the request, and why), or the status alone
    when the answer names neither."""
    said = ""
    if isinstance(problem, dict):
        detail = problem.get("detail")
        if problem.get("code"):
            said = str(problem["code"])
            if isinstance(detail, str) and detail:
                said = f"{said} ({detail})"
        elif isinstance(detail, list) and detail and isinstance(detail[0], dict):
            where = ".".join(str(part) for part in detail[0].get("loc", []))
            said = f"{where}: {detail[0].get('msg', '')}".strip(": ")
    return f"{method} {path}: {status} {said}".strip()


@dataclass(frozen=True)
class Arrival:
    """Where a person arrives in a world's region and the way they face, in the region's frame:
    east, height and south in millimetres, and a facing vector east then south."""

    region_id: str
    at_mm: tuple[int, int, int]
    facing: tuple[float, float]

    def pose(self, place: Mapping[str, int]) -> dict[str, int]:
        """A place stated from this arrival, as a pose in the region's frame. A placed object's own
        z axis points south at yaw 0 and its yaw turns counterclockwise seen from above, as the
        renderer turns every placed object: at a turn of 0 the thing faces the person arriving."""
        east, south = self.facing
        length = math.hypot(east, south)
        forward = (east / length, south / length)
        right = (-forward[1], forward[0])
        x = self.at_mm[0] + place["right_mm"] * right[0] + place["forward_mm"] * forward[0]
        z = self.at_mm[2] + place["right_mm"] * right[1] + place["forward_mm"] * forward[1]
        facing = round(math.atan2(-forward[0], -forward[1]) * 1_000_000)
        yaw = (place["turn_microradians"] + facing) % (FULL_TURN + 1)
        return {"x_mm": round(x), "y_mm": self.at_mm[1], "z_mm": round(z), "yaw_microradians": yaw}


def arrival_of(entry: Mapping[str, Any]) -> Arrival:
    """The arrival a saved world's entry states: a starter's spawn, or a generated town's or site's
    arrival point and facing."""
    for key in ("generated_ground", "generated_site"):
        ground = entry.get(key)
        if ground:
            return Arrival(
                ground["region_id"], tuple(ground["arrival_mm"]), tuple(ground["arrival_facing_mm"])
            )
    scene = entry.get("authored_scene")
    if scene:
        region = scene["region"]
        spawn = region["spawn"]
        theta = spawn["yaw_microradians"] / 1_000_000
        return Arrival(
            region["region_id"],
            (spawn["x_mm"], spawn["y_mm"], spawn["z_mm"]),
            (-math.sin(theta), -math.cos(theta)),
        )
    raise SceneRefused("the saved world states no arrival to place things from")


def _stored_pose(placed: Mapping[str, Any]) -> dict[str, int]:
    transform = placed["transform"]
    return {
        "x_mm": transform["x_mm"],
        "y_mm": transform["y_mm"],
        "z_mm": transform["z_mm"],
        "yaw_microradians": transform["yaw_microradians"],
    }


def _placed(version: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {thing["thing_id"]: thing for thing in version.get("things", []) if not thing["removed"]}


def build(api: Api, scene: Mapping[str, Any], entry_id: str | None = None) -> dict[str, Any]:
    if entry_id is None:
        if scene["ground"]["kind"] != "starter":
            raise SceneRefused("name the saved world to dress with --entry")
        entry = api.call("POST", "/world-entries/starter", {"title": scene["title"]})
    else:
        entry = api.call("GET", f"/world-entries/{entry_id}")
    world_id = entry["world_id"]
    version_id = entry["authored_version_id"]
    arrival = arrival_of(entry)
    region = arrival.region_id
    poses = {thing["thing_id"]: arrival.pose(thing["place"]) for thing in scene["things"]}
    version = api.call("GET", f"/world/versions/{version_id}", world_id=world_id)
    added = 0
    for thing in scene["things"]:
        already = _placed(version).get(thing["thing_id"])
        wanted = {"kind": thing["kind"]["kind"], "version": thing["kind"]["version"]}
        if already is not None:
            stored = {"kind": already["kind"]["kind"], "version": already["kind"]["version"]}
            if stored != wanted or _stored_pose(already) != poses[thing["thing_id"]]:
                raise SceneRefused(f"{thing['thing_id']} is placed already, as something else")
            continue
        entry = api.call("GET", f"/world-entries/{entry['entry_id']}")
        body = {
            "base_state_sha256": version["state_sha256"],
            "saved_entry": {
                "entry_id": entry["entry_id"],
                "base_revision": entry["revision"],
                "authored_state_sha256": entry["authored_state_sha256"],
                "authored_edit_seq": entry["authored_edit_seq"],
            },
            "thing_id": thing["thing_id"],
            "kind": wanted,
            "region_id": region,
            "pose": poses[thing["thing_id"]],
            "origin_role": "fictional",
        }
        version = api.call("POST", f"/world/versions/{version_id}/things", body, world_id=world_id)
        added += 1
    version = api.call("GET", f"/world/versions/{version_id}", world_id=world_id)
    placed = _placed(version)
    for thing in scene["things"]:
        stored = placed.get(thing["thing_id"])
        if stored is None:
            raise SceneRefused(f"{thing['thing_id']} is not in the version read back")
        if (stored["kind"]["kind"], stored["kind"]["version"]) != (
            thing["kind"]["kind"],
            thing["kind"]["version"],
        ):
            raise SceneRefused(f"{thing['thing_id']} reads back as another kind")
        if stored["region_id"] != region or _stored_pose(stored) != poses[thing["thing_id"]]:
            raise SceneRefused(f"{thing['thing_id']} reads back somewhere else")
    entry = api.call("GET", f"/world-entries/{entry['entry_id']}")
    if (entry["authored_state_sha256"], entry["authored_edit_seq"]) != (
        version["state_sha256"],
        version["edit_seq"],
    ):
        raise SceneRefused("the saved world does not reopen at the version built")
    record = {
        "profile": RECORD_PROFILE,
        "scene": {"scene": scene["scene"], "version": scene["version"], "sha256": _digest(scene)},
        "built_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "world_id": world_id,
        "arrival": {
            "region_id": region,
            "at_mm": list(arrival.at_mm),
            "facing": list(arrival.facing),
        },
        "entry_id": entry["entry_id"],
        "version_id": version_id,
        "state_sha256": version["state_sha256"],
        "edit_seq": version["edit_seq"],
        "things_added": added,
        "things": [
            {
                "thing_id": thing["thing_id"],
                "kind": placed[thing["thing_id"]]["kind"],
                "region_id": region,
                "pose": poses[thing["thing_id"]],
            }
            for thing in scene["things"]
        ],
        "minds": list(scene.get("minds", [])),
        "engine": scene.get("engine"),
    }
    if "travellers" in scene:
        # The gate travellers come through and the mind they are given: whoever opens the gate
        # (a game's own tool, or the world's owner) passes them to the door's grant. This script
        # opens no gate and holds no grant's key.
        record["travellers"] = scene["travellers"]
    return record


def _model(decider: Mapping[str, Any]) -> dict[str, str] | None:
    """The model a scene's decider names, or None for the routine."""
    if decider["kind"] == "routine":
        return None
    if decider["kind"] != "model":
        raise SceneRefused(f"a scene chooses a model or the routine, not {decider['kind']!r}")
    return {"provider": decider["provider"], "model_id": decider["model_id"]}


def bring_to_life(api: Api, scene: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    """Start the scene's society on the version ``record`` built and choose each being's mind, as
    the world's owner would; the choices are read back. Returns what the record keeps of it."""
    world_id, version_id = record["world_id"], record["version_id"]
    society_path = f"/world/versions/{version_id}/society"
    society = api.call(
        "POST",
        society_path,
        {"region_id": record["arrival"]["region_id"], "profile": scene["engine"]},
        world_id=world_id,
    )
    if society["profile"] != scene["engine"]:
        raise SceneRefused(
            f"the version's society runs {society['profile']}, not {scene['engine']}"
        )
    people = {
        person["placed_id"]: person["id"]
        for person in society["state"]["inhabitants"]
        if person.get("came_by") == "placed"
    }
    chosen = []
    for mind in scene.get("minds", []):
        person = people.get(mind["thing_id"])
        if person is None:
            raise SceneRefused(f"{mind['thing_id']} is not among the society's people")
        model = _model(mind["decider"])
        key = mind_key(record["scene"]["sha256"], society["society_id"], mind["thing_id"])
        api.call(
            "POST",
            f"{society_path}/models",
            {"idempotency_key": str(key), "people": [person], "model": model},
            world_id=world_id,
        )
        chosen.append({"thing_id": mind["thing_id"], "person_id": person, "model": model})
    view = api.call("GET", f"{society_path}/models", world_id=world_id)
    held = {choice["subject_id"]: choice["model"] for choice in view["choices"]}
    for choice in chosen:
        stored = held.get(choice["person_id"])
        if stored is not None:
            stored = {"provider": stored["provider"], "model_id": stored["model_id"]}
        if stored != choice["model"]:
            raise SceneRefused(f"{choice['thing_id']}'s mind reads back as another")
    return {
        "society_id": society["society_id"],
        "engine": society["profile"],
        "state_sha256": society["state_sha256"],
        # Why no model would be asked here (no key, no allowance), as the server says; None when
        # the chosen models are asked.
        "host_refusal": view.get("host_refusal"),
        "minds": chosen,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("scene", type=Path, help="the scene document")
    parser.add_argument("--base-url", required=True, help="the API's address")
    parser.add_argument("--record", type=Path, required=True, help="where to write the record")
    parser.add_argument("--entry", help="the saved world to dress; a starter is made without it")
    parser.add_argument(
        "--minds",
        action="store_true",
        help="then start the scene's society and choose each being's mind",
    )
    args = parser.parse_args(argv)
    token = os.environ.get("EXULANICA_TOKEN")
    if not token:
        print("set EXULANICA_TOKEN to a token with world.read and world.write", file=sys.stderr)
        return 2
    try:
        api = Api(args.base_url, token)
        scene = read_scene(args.scene)
        record = build(api, scene, args.entry)
        if args.minds:
            record["society"] = bring_to_life(api, scene, record)
    except SceneRefused as refused:
        print(f"not built: {refused}", file=sys.stderr)
        return 1
    args.record.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(
        f"built {record['scene']['scene']} v{record['scene']['version']}: "
        f"{len(record['things'])} things ({record['things_added']} added), "
        f"version {record['version_id']} at edit {record['edit_seq']}"
    )
    if "society" in record:
        society = record["society"]
        print(f"society {society['society_id']} on {society['engine']}: ", end="")
        print(
            ", ".join(
                f"{m['thing_id']} {(m['model'] or {}).get('model_id', 'routine')}"
                for m in society["minds"]
            )
        )
        if society["host_refusal"]:
            print(f"no model is asked here yet: {society['host_refusal']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
