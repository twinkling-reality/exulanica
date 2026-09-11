"""A second client for the world API: read a named version, add a reviewed object, move it.

    EXULANICA_TOKEN=<bearer token> uv run python scripts/world_client_example.py \
      --base-url http://127.0.0.1:8001 --version <version uuid> --origin-role fictional \
      --motion travel_mm=600,period_milliseconds=3000,axis=x,easing=smooth \
      --demonstrate-stale-base --transcript /tmp/world-client.json

**Why this exists.** The product roadmap will not claim interoperability until a tool other
than the browser makes an accepted change through the authenticated API without depending on
private interface state. This is that tool, kept small enough to read in one sitting. It uses
the standard library and httpx and imports nothing from ``exulanica``; everything it knows
comes from the HTTP contract in ``docs/world-objects-contract.md`` sections 5 to 7.

**What it does, in order.**

1.  Reads the named alternate version and its objects. The ``state_sha256`` it gets back is
    the base every edit must name.
2.  Reads the reviewed asset registry and refuses to place an asset whose bytes the server
    reports unavailable, because a renderer could not draw it.
3.  Adds one object against that base, then moves it against the base the add returned.
4.  Handles ``409 stale_object_base`` by re-reading the version and reconciling: it re-issues
    the edit only if the object is still exactly where this client last saw it, and otherwise
    stops and says what changed underneath it. It never retries blind, because a blind retry is
    the lost update the compare-and-swap exists to prevent. ``--demonstrate-stale-base``
    presents the pre-add token for the move on purpose, so the refusal path is exercised and
    shown rather than asserted.
5.  Reads the version again and prints what changed: objects added and moved, the edits
    appended, and the state token before and after.

The bearer token is read from an environment variable and is never printed or written to the
transcript; neither is any actor id the server returns.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx

REGION_LOCAL_KEYS = ("x_mm", "y_mm", "z_mm", "yaw_microradians", "scale_milli")


class ClientStop(Exception):
    """The client refuses to continue, with a reason a person can act on."""


@dataclass
class Transcript:
    """What happened on the wire, without the credential and without actor ids."""

    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, step: str, response: httpx.Response, *, sent: Any = None, note: str = "") -> None:
        body = _json(response)
        entry: dict[str, Any] = {
            "method": response.request.method,
            "path": response.request.url.path,
            "status": response.status_code,
            "step": step,
        }
        if sent is not None:
            entry["request_body"] = sent
        if isinstance(body, dict) and "code" in body:
            entry["problem"] = {"code": body["code"], "detail": body.get("detail")}
        elif isinstance(body, dict) and "state_sha256" in body:
            entry["version"] = summarise(body)
        if note:
            entry["note"] = note
        self.entries.append(entry)
        status = f"{response.status_code}"
        if "problem" in entry:
            status += f" {entry['problem']['code']}"
        print(f"{step:<8} {response.request.method} {response.request.url.path} -> {status}"
              + (f"  ({note})" if note else ""))


class WorldClient:
    """Every request carries the bearer token; nothing else about the session is kept."""

    def __init__(self, http: httpx.Client, token: str, transcript: Transcript) -> None:
        self._http = http
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self.transcript = transcript

    def get(self, step: str, path: str, *, note: str = "") -> Any:
        response = self._http.get(path, headers=self._headers)
        self.transcript.record(step, response, note=note)
        if response.status_code != 200:
            raise ClientStop(f"GET {path} answered {response.status_code}: {_json(response)}")
        return response.json()

    def post(self, step: str, path: str, body: dict[str, Any], *, note: str = "") -> httpx.Response:
        response = self._http.post(path, json=body, headers=self._headers)
        self.transcript.record(step, response, sent=body, note=note)
        return response


def summarise(version: dict[str, Any]) -> dict[str, Any]:
    """The part of a version body a person needs to see, with no actor id in it."""
    return {
        "edit_seq": version["edit_seq"],
        "edits": [
            {
                "base_state_sha256": edit["base_state_sha256"],
                "edit_seq": edit["edit_seq"],
                "kind": edit["kind"],
                "object_id": edit["object_id"],
                "result_state_sha256": edit["result_state_sha256"],
            }
            for edit in version["edits"]
        ],
        "objects": [
            {
                "asset_key": obj["asset"]["asset_key"],
                "availability": obj["asset"]["availability"],
                "behaviour": obj["behaviour"],
                "content_sha256": obj["asset"]["content_sha256"],
                "object_id": obj["object_id"],
                "origin": obj["origin"],
                "region_id": obj["region_id"],
                "removed": obj["removed"],
                "transform": obj["transform"],
            }
            for obj in version["objects"]
        ],
        "source_invalidated": version["source_invalidated"],
        "source_snapshot_id": version["source_snapshot_id"],
        "state_sha256": version["state_sha256"],
        "title": version["title"],
        "version_id": version["version_id"],
    }


def resolve_version(client: WorldClient, version_id: str | None, title: str | None) -> dict[str, Any]:
    if version_id:
        return client.get("read", f"/world/versions/{version_id}")
    versions = client.get("list", "/world/versions")
    named = [version for version in versions if version["title"] == title]
    if len(named) != 1:
        raise ClientStop(
            f"{len(named)} versions are titled {title!r}; name one by --version. Known: "
            + ", ".join(f"{v['version_id']} {v['title']!r}" for v in versions)
        )
    return client.get("read", f"/world/versions/{named[0]['version_id']}")


def choose_asset(client: WorldClient, asset_key: str) -> dict[str, Any]:
    catalog = client.get("assets", "/world/assets")
    for asset in catalog:
        if asset["asset_key"] == asset_key:
            if asset["availability"] != "available":
                raise ClientStop(
                    f"{asset_key} is {asset['availability']}: its reviewed bytes are missing, so "
                    "there is nothing a renderer could draw. Not placing it."
                )
            return asset
    raise ClientStop(f"{asset_key} is not in the reviewed registry: {[a['asset_key'] for a in catalog]}")


def choose_region(client: WorldClient, version: dict[str, Any], region: str | None) -> str:
    """An explicit region, else one an object already uses, else a protected source region.

    The version body does not list its source snapshot's regions, so a client that has placed
    nothing yet learns one from ``GET /world/source-media``. The server validates it either way
    and answers 422 for a region the source snapshot does not have.
    """
    if region:
        return region
    for obj in version["objects"]:
        return obj["region_id"]
    for slot in client.get("regions", "/world/source-media"):
        if slot["region_id"]:
            return slot["region_id"]
    raise ClientStop("no region is known; pass --region")


def edit(
    client: WorldClient,
    step: str,
    path: str,
    body: dict[str, Any],
    *,
    version_path: str,
    last_seen_state: str,
    still_applies: Any,
    note: str = "",
) -> tuple[dict[str, Any], str]:
    """Submit one edit; on a stale base, re-read, reconcile, and re-issue at most once.

    Returns the version the accepted edit produced and the base it was accepted against.

    ``last_seen_state`` is the newest state this client itself produced or read. After a
    refusal the re-read either still shows it, which means the refused edit changed nothing and
    nobody else wrote, or it does not, which means another writer did and ``still_applies``
    decides whether this edit survives what they did.
    """
    response = client.post(step, path, body, note=note)
    if response.status_code in (200, 201):
        return response.json(), body["base_state_sha256"]
    problem = _json(response)
    if response.status_code != 409 or problem.get("code") != "stale_object_base":
        raise ClientStop(f"{step} refused: {response.status_code} {problem}")
    fresh = client.get("reread", version_path)
    client.transcript.entries[-1]["note"] = (
        "state is the one this client last saw: the refused edit changed nothing"
        if fresh["state_sha256"] == last_seen_state
        else "state moved on: another writer edited the version since this client last read it"
    )
    print(f"         {client.transcript.entries[-1]['note']}")
    reason = still_applies(fresh)
    if reason:
        raise ClientStop(f"{step} no longer applies after re-reading: {reason}")
    retried = {**body, "base_state_sha256": fresh["state_sha256"]}
    response = client.post(step, path, retried, note="re-issued against the re-read base")
    if response.status_code not in (200, 201):
        raise ClientStop(f"{step} refused again: {response.status_code} {_json(response)}")
    return response.json(), fresh["state_sha256"]


def what_changed(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    previous = {obj["object_id"]: obj for obj in before["objects"]}
    current = {obj["object_id"]: obj for obj in after["objects"]}
    added = sorted(set(current) - set(previous))
    moved = sorted(
        object_id
        for object_id in set(current) & set(previous)
        if _pose(current[object_id]) != _pose(previous[object_id])
    )
    removed = sorted(
        object_id
        for object_id in set(current) & set(previous)
        if current[object_id]["removed"] and not previous[object_id]["removed"]
    )
    return {
        "added": [
            {
                "asset_key": current[i]["asset"]["asset_key"],
                "behaviour": current[i]["behaviour"],
                "content_sha256": current[i]["asset"]["content_sha256"],
                "object_id": i,
                "origin": current[i]["origin"],
                "region_id": current[i]["region_id"],
                "transform": current[i]["transform"],
            }
            for i in added
        ],
        "edits_appended": [
            {
                "base_state_sha256": e["base_state_sha256"],
                "edit_seq": e["edit_seq"],
                "kind": e["kind"],
                "object_id": e["object_id"],
                "result_state_sha256": e["result_state_sha256"],
            }
            for e in after["edits"]
            if e["edit_seq"] > before["edit_seq"]
        ],
        "moved": [
            {"from": _pose(previous[i]), "object_id": i, "to": _pose(current[i])} for i in moved
        ],
        "removed": removed,
        "state_sha256": {"after": after["state_sha256"], "before": before["state_sha256"]},
    }


def main(argv: list[str] | None = None, *, http: httpx.Client | None = None) -> int:
    """Run the client. ``http`` lets a test hand in its own transport; otherwise one is made."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--base-url", default=os.environ.get("EXULANICA_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token-env", default="EXULANICA_TOKEN", help="environment variable holding the bearer token")
    named = parser.add_mutually_exclusive_group(required=True)
    named.add_argument("--version", help="the alternate version id to edit")
    named.add_argument("--title", help="the alternate version title, which must be unique")
    parser.add_argument("--asset-key", default="cc0.marker-cube")
    parser.add_argument("--region")
    parser.add_argument("--object-id", default=f"second-client:marker-{secrets.token_hex(4)}")
    parser.add_argument(
        "--origin-role", required=True, choices=("fictional", "personal"),
        help="chosen by the person; the server never infers it",
    )
    parser.add_argument("--place", default="1500,0,-800", help="region-local x,y,z in millimetres")
    parser.add_argument("--move-by", default="750,0,0", help="x,y,z millimetres to move by")
    parser.add_argument("--motion", help="attach motion.bounded-path@1 with key=value,... parameters")
    parser.add_argument("--demonstrate-stale-base", action="store_true")
    parser.add_argument("--transcript", help="write the wire transcript as JSON to this path")
    args = parser.parse_args(argv)

    token = os.environ.get(args.token_env, "")
    if not token:
        print(f"set {args.token_env} to a bearer token; it is never printed", file=sys.stderr)
        return 2
    transcript = Transcript()
    owned = http is None
    if http is None:
        http = httpx.Client(base_url=args.base_url.rstrip("/"), timeout=30.0)
    client = WorldClient(http, token, transcript)
    outcome: dict[str, Any] = {"transcript": transcript.entries}
    try:
        before = resolve_version(client, args.version, args.title)
        version_path = f"/world/versions/{before['version_id']}"
        print(
            f"         version {before['version_id']} {before['title']!r}: "
            f"{len(before['objects'])} object(s), edit_seq {before['edit_seq']}, "
            f"base {before['state_sha256']}"
        )
        if before["source_invalidated"]:
            raise ClientStop("the version's source was deleted; branch from a live snapshot instead")
        asset = choose_asset(client, args.asset_key)
        region = choose_region(client, before, args.region)
        x, y, z = (int(value) for value in args.place.split(","))
        dx, dy, dz = (int(value) for value in args.move_by.split(","))
        placed = {"scale_milli": 1000, "x_mm": x, "y_mm": y, "yaw_microradians": 0, "z_mm": z}
        destination = {**placed, "x_mm": x + dx, "y_mm": y + dy, "z_mm": z + dz}
        add_body: dict[str, Any] = {
            "asset_sha256": asset["content_sha256"],
            "base_state_sha256": before["state_sha256"],
            "object_id": args.object_id,
            "origin_role": args.origin_role,
            "region_id": region,
            "transform": placed,
        }
        if args.motion:
            add_body["behaviour"] = {
                "behaviour_key": "motion.bounded-path",
                "behaviour_version": 1,
                "parameters": _parameters(args.motion),
            }
        added, add_base = edit(
            client,
            "add",
            f"{version_path}/objects",
            add_body,
            version_path=version_path,
            last_seen_state=before["state_sha256"],
            still_applies=lambda fresh: (
                f"{args.object_id} now exists"
                if any(o["object_id"] == args.object_id for o in fresh["objects"])
                else None
            ),
            note=f"base {before['state_sha256']}",
        )
        move_base = before["state_sha256"] if args.demonstrate_stale_base else added["state_sha256"]
        moved, move_accepted_base = edit(
            client,
            "move",
            f"{version_path}/objects/{args.object_id}/move",
            {"base_state_sha256": move_base, "transform": destination},
            version_path=version_path,
            last_seen_state=added["state_sha256"],
            still_applies=lambda fresh: _unchanged_since(fresh, args.object_id, placed),
            note=(
                "deliberately presenting the pre-add base, which the add made stale"
                if args.demonstrate_stale_base
                else f"base {move_base}"
            ),
        )
        after = client.get("final", version_path)
        if after["state_sha256"] != moved["state_sha256"]:
            print("         note: another writer changed the version after this client's move")
        outcome.update(
            {
                "after": summarise(after),
                "base_version": {
                    "state_sha256": before["state_sha256"],
                    "version_id": before["version_id"],
                },
                "before": summarise(before),
                "changed": what_changed(before, after),
                "result": "accepted",
                "this_client": [
                    {
                        "at": _pose(_find(added, args.object_id)),
                        "base_state_sha256": add_base,
                        "edit": "add_object",
                        "object_id": args.object_id,
                        "result_state_sha256": added["state_sha256"],
                    },
                    {
                        "base_state_sha256": move_accepted_base,
                        "edit": "move_object",
                        "from": _pose(_find(added, args.object_id)),
                        "object_id": args.object_id,
                        "refused_first_with_stale_base": move_base != move_accepted_base,
                        "result_state_sha256": moved["state_sha256"],
                        "to": _pose(_find(moved, args.object_id)),
                    },
                ],
            }
        )
        _print_changes(outcome["changed"], outcome["this_client"])
        return_code = 0
    except ClientStop as stop:
        print(f"stopped: {stop}", file=sys.stderr)
        outcome.update({"result": "stopped", "reason": str(stop)})
        return_code = 1
    finally:
        if owned:
            http.close()
    if args.transcript:
        with open(args.transcript, "w", encoding="utf-8") as handle:
            json.dump(outcome, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return return_code


def _unchanged_since(fresh: dict[str, Any], object_id: str, expected: dict[str, int]) -> str | None:
    """Why a move made against a stale base no longer applies, or None when it still does."""
    for obj in fresh["objects"]:
        if obj["object_id"] == object_id:
            if obj["removed"]:
                return f"{object_id} was removed by another edit"
            if _pose(obj) != expected:
                return f"{object_id} was moved by another edit to {_pose(obj)}"
            return None
    return f"{object_id} is no longer in the version"


def _find(version: dict[str, Any], object_id: str) -> dict[str, Any]:
    for obj in version["objects"]:
        if obj["object_id"] == object_id:
            return obj
    raise ClientStop(f"{object_id} is missing from the version the server returned")


def _pose(obj: dict[str, Any]) -> dict[str, int]:
    return {key: obj["transform"][key] for key in REGION_LOCAL_KEYS}


def _parameters(text: str) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    for pair in text.split(","):
        key, _, value = pair.partition("=")
        parameters[key.strip()] = int(value) if value.strip().lstrip("-").isdigit() else value.strip()
    return parameters


def _print_changes(changed: dict[str, Any], own: list[dict[str, Any]]) -> None:
    print("what this client did:")
    for step in own:
        if step["edit"] == "add_object":
            at = step["at"]
            print(
                f"  add  {step['object_id']} at ({at['x_mm']}, {at['y_mm']}, {at['z_mm']}) mm, "
                f"base {step['base_state_sha256'][:12]} -> {step['result_state_sha256'][:12]}"
            )
        else:
            start, end = step["from"], step["to"]
            print(
                f"  move {step['object_id']} ({start['x_mm']}, {start['y_mm']}, {start['z_mm']}) -> "
                f"({end['x_mm']}, {end['y_mm']}, {end['z_mm']}) mm, "
                f"base {step['base_state_sha256'][:12]} -> {step['result_state_sha256'][:12]}"
                + ("  (accepted after a stale-base refusal and a re-read)"
                   if step["refused_first_with_stale_base"] else "")
            )
    print("what changed in the version, first read to last:")
    for obj in changed["added"]:
        pose = obj["transform"]
        behaviour = obj["behaviour"]
        print(
            f"  + {obj['object_id']}  {obj['asset_key']} {obj['content_sha256'][:12]}  "
            f"region {obj['region_id']}  at ({pose['x_mm']}, {pose['y_mm']}, {pose['z_mm']}) mm"
            f"  origin {obj['origin']['kind']}/{obj['origin']['role']}"
            + (
                f"  behaviour {behaviour['behaviour_key']}@{behaviour['behaviour_version']} "
                f"{json.dumps(behaviour['parameters'], sort_keys=True)}"
                if behaviour
                else ""
            )
        )
    for move in changed["moved"]:
        start, end = move["from"], move["to"]
        print(
            f"  ~ {move['object_id']}  moved ({start['x_mm']}, {start['y_mm']}, {start['z_mm']})"
            f" -> ({end['x_mm']}, {end['y_mm']}, {end['z_mm']}) mm"
        )
    for object_id in changed["removed"]:
        print(f"  - {object_id}  removed")
    for e in changed["edits_appended"]:
        print(
            f"  edit {e['edit_seq']} {e['kind']} {e['object_id']}: "
            f"{e['base_state_sha256'][:12]} -> {e['result_state_sha256'][:12]}"
        )
    state = changed["state_sha256"]
    print(f"  state {state['before']} -> {state['after']}")


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"body": response.text[:500]}


if __name__ == "__main__":
    raise SystemExit(main())
