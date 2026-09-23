"""The developer proof: read a saved world, find out what it supports, edit it, and check the edit.

    EXULANICA_TOKEN=<token> python -m exulanica_client walkthrough \\
        --base-url http://127.0.0.1:8000 --origin-role fictional --place 0,0,2000 \\
        --transcript walkthrough.json

In order, stopping at the first thing that is not as expected and saying why:

1.  Discover. The edits the server documents, its reviewed behaviours and its reviewed assets
    (:mod:`exulanica_client.discovery`). Placing an object and setting a behaviour must both be
    among the edits, or the walkthrough stops before sending anything.
2.  Read the saved world and the version it opens at. Its resume point must be the version's
    current state, because an edit bound to a saved world starts from exactly there.
3.  Place one reviewed object against the state just read, advancing the saved world with it.
4.  Give that object motion: a reviewed behaviour, with parameters inside the server's bounds.
5.  Ask for a behaviour the server does not list, and record the server's refusal and its reason.
6.  Read the version and the saved world again, and check every fact the edits claimed, including
    that the refused request changed nothing.

The origin role has no default: whether an object is fictional or personal is the person's choice,
and the server never infers it. The transcript holds every exchange except the credential, and no
actor id the server returns.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .client import ApiRefusal, ClientError, Exchange, WorldClient
from .discovery import (
    Behaviour,
    Operation,
    parse_behaviour_identity,
    reviewed_behaviours,
    version_edits,
)

__all__ = ["main"]

#: The two edits this walkthrough makes, by the method and path the server documents them under.
PLACE_OBJECT = ("POST", "/world/versions/{version_id}/objects")
SET_BEHAVIOUR = ("POST", "/world/versions/{version_id}/objects/{object_id}/behaviour")
#: A placed object faces the region's own axes at its reviewed size: no turn, scale one to one.
UPRIGHT_YAW_MICRORADIANS = 0
REVIEWED_SIZE_SCALE_MILLI = 1000
#: Response fields that name who acted. A transcript is meant to be shared, so they are dropped.
_ACTOR_FIELDS = frozenset({"actor", "created_by", "attached_by", "detached_by"})
_EXIT_CONFIRMED, _EXIT_STOPPED, _EXIT_USAGE = 0, 1, 2


class Stop(Exception):
    """The walkthrough cannot continue, with the reason a person can act on."""


@dataclass
class Transcript:
    """What happened on the wire and what it showed. Never the credential; never an actor id."""

    exchanges: list[dict[str, Any]] = field(default_factory=list)
    step: str = "start"

    def record(self, exchange: Exchange) -> None:
        entry: dict[str, Any] = {
            "step": self.step,
            "method": exchange.method,
            "path": exchange.path,
            "status": exchange.status,
        }
        if exchange.query:
            entry["query"] = dict(exchange.query)
        if exchange.request_body is not None:
            entry["request_body"] = _without_actors(exchange.request_body)
        entry.update(_answer_summary(exchange))
        self.exchanges.append(entry)
        problem = entry.get("problem")
        print(
            f"  {exchange.method} {exchange.path} -> {exchange.status}"
            + (f" {problem['code']}: {problem['detail']}" if problem else "")
        )


def _answer_summary(exchange: Exchange) -> dict[str, Any]:
    body = exchange.response_body
    if isinstance(body, dict) and "code" in body and exchange.status >= 400:
        return {"problem": {"code": body.get("code"), "detail": body.get("detail")}}
    if isinstance(body, dict) and "state_sha256" in body and "objects" in body:
        return {"version": _version_summary(body)}
    if isinstance(body, dict) and "entry_id" in body:
        return {"saved_world": _entry_summary(body)}
    if isinstance(body, dict) and "openapi" in body:
        return {"openapi": {"version": body.get("openapi"), "info": body.get("info")}}
    if isinstance(body, list):
        return {"items": len(body)}
    return {}


def _version_summary(version: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version_id": version["version_id"],
        "world_id": version["world_id"],
        "state_sha256": version["state_sha256"],
        "edit_seq": version["edit_seq"],
        "objects": [
            {
                "object_id": obj["object_id"],
                "asset_key": obj["asset"]["asset_key"],
                "content_sha256": obj["asset"]["content_sha256"],
                "region_id": obj["region_id"],
                "transform": obj["transform"],
                "origin": obj["origin"],
                "behaviour": obj["behaviour"],
                "removed": obj["removed"],
            }
            for obj in version["objects"]
        ],
        "edits": [
            {
                "edit_seq": edit["edit_seq"],
                "kind": edit["kind"],
                "object_id": edit["object_id"],
                "base_state_sha256": edit["base_state_sha256"],
                "result_state_sha256": edit["result_state_sha256"],
            }
            for edit in version["edits"]
        ],
    }


def _entry_summary(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: entry.get(key)
        for key in (
            "entry_id",
            "title",
            "world_id",
            "source_kind",
            "authored_version_id",
            "authored_state_sha256",
            "authored_edit_seq",
            "revision",
            "availability",
        )
    }


def _without_actors(value: object) -> object:
    if isinstance(value, dict):
        return {k: _without_actors(v) for k, v in value.items() if k not in _ACTOR_FIELDS}
    if isinstance(value, list):
        return [_without_actors(item) for item in value]
    return value


# -- choices, each made from what the server reported ----------------------------------------------


def _choose_saved_world(worlds: Sequence[Mapping[str, Any]], args: argparse.Namespace) -> dict:
    if args.entry:
        named = [world for world in worlds if world["entry_id"] == args.entry]
    elif args.title:
        named = [world for world in worlds if world["title"] == args.title]
    else:
        named = list(worlds)
    if len(named) != 1:
        known = ", ".join(f"{w['entry_id']} {w['title']!r}" for w in worlds) or "none"
        raise Stop(
            f"{len(named)} saved worlds match; name one with --entry or --title. Known: {known}"
        )
    world = dict(named[0])
    if world["availability"] != "available":
        raise Stop(f"the saved world is unavailable: {world.get('unavailable_reason')}")
    return world


def _choose_asset(assets: Sequence[Mapping[str, Any]], asset_key: str | None) -> dict:
    available = [asset for asset in assets if asset["availability"] == "available"]
    if asset_key is not None:
        named = [asset for asset in assets if asset["asset_key"] == asset_key]
        if not named:
            raise Stop(
                f"{asset_key} is not a reviewed asset here: {[a['asset_key'] for a in assets]}"
            )
        if named[0]["availability"] != "available":
            raise Stop(
                f"{asset_key} is {named[0]['availability']}: its reviewed bytes are missing on "
                "this server, so nothing could draw it"
            )
        return dict(named[0])
    if len(available) != 1:
        raise Stop(
            "name the asset to place with --asset-key; available here: "
            + (", ".join(a["asset_key"] for a in available) or "none")
        )
    return dict(available[0])


def _choose_behaviour(behaviours: Sequence[Behaviour], identity: str | None) -> Behaviour:
    if identity is not None:
        try:
            key, version = parse_behaviour_identity(identity)
        except ValueError as malformed:
            raise Stop(str(malformed)) from None
        for behaviour in behaviours:
            if (behaviour.key, behaviour.version) == (key, version):
                return behaviour
        raise Stop(
            f"{identity} is not a behaviour this server reviews: "
            + (", ".join(b.identity for b in behaviours) or "none")
        )
    if len(behaviours) != 1:
        raise Stop(
            "name the behaviour with --behaviour KEY@VERSION; reviewed here: "
            + (", ".join(b.identity for b in behaviours) or "none")
        )
    return behaviours[0]


def _parameters(behaviour: Behaviour, overrides: Sequence[str]) -> dict[str, Any]:
    """The registry's declared defaults, with each ``NAME=VALUE`` read as that parameter's kind."""
    values = behaviour.defaults()
    for pair in overrides:
        name, separator, text = pair.partition("=")
        if not separator or name not in behaviour.parameters:
            raise Stop(f"{pair!r} is not NAME=VALUE for a parameter of {behaviour.identity}")
        kind = behaviour.parameters[name].get("kind")
        if kind == "integer":
            try:
                values[name] = int(text)
            except ValueError:
                raise Stop(f"{name} must be an integer, not {text!r}") from None
        elif kind == "toggle":
            values[name] = {"true": True, "false": False}.get(text.lower(), text)
        else:
            values[name] = text
    problems = behaviour.problems(values)
    if problems:
        raise Stop(f"the server would refuse these parameters: {'; '.join(problems)}")
    return values


def _region(world: Mapping[str, Any], version: Mapping[str, Any], region: str | None) -> str:
    """An explicit region, else the saved world's authored region, else one an object uses."""
    if region:
        return region
    scene = world.get("authored_scene") or {}
    if scene.get("region", {}).get("region_id"):
        return scene["region"]["region_id"]
    for obj in version["objects"]:
        return obj["region_id"]
    raise Stop("no region is known for this saved world; pass --region")


def _unlisted_version(behaviours: Sequence[Behaviour], key: str) -> int:
    """A version of ``key`` the server's registry does not list: one past the newest it does."""
    return max(b.version for b in behaviours if b.key == key) + 1


def _find(version: Mapping[str, Any], object_id: str) -> Mapping[str, Any] | None:
    return next((obj for obj in version["objects"] if obj["object_id"] == object_id), None)


# -- the walkthrough -------------------------------------------------------------------------------


def discover(client: WorldClient) -> tuple[list[Operation], list[Behaviour], list[dict]]:
    edits = version_edits(client.openapi())
    behaviours = reviewed_behaviours(client.behaviours())
    assets = client.assets()
    return edits, behaviours, assets


def _print_discovery(
    edits: Sequence[Operation], behaviours: Sequence[Behaviour], assets: Sequence[Mapping]
) -> None:
    print("edits this server documents for an authored version:")
    for edit in edits:
        print(f"  {edit.method} {edit.path}  ({edit.summary})")
    print("behaviours it reviews:")
    for behaviour in behaviours:
        print(f"  {behaviour.describe()}")
    print("assets it can place:")
    for asset in assets:
        print(f"  {asset['asset_key']} {asset['availability']} {asset['content_sha256'][:12]}")


def walkthrough(
    client: WorldClient, transcript: Transcript, args: argparse.Namespace, outcome: dict[str, Any]
) -> None:
    """Run the six steps, writing what each one learns into ``outcome`` as it goes."""

    transcript.step = "discover"
    edits, behaviours, assets = discover(client)
    _print_discovery(edits, behaviours, assets)
    documented = {(edit.method, edit.path) for edit in edits}
    for needed, label in ((PLACE_OBJECT, "placing an object"), (SET_BEHAVIOUR, "giving it motion")):
        if needed not in documented:
            raise Stop(f"this server does not document {label} ({' '.join(needed)})")
    outcome["discovered"] = {
        "edits": [edit.__dict__ for edit in edits],
        "behaviours": [
            {"key": b.key, "version": b.version, "parameters": dict(b.parameters)}
            for b in behaviours
        ],
        "assets": [
            {key: asset[key] for key in ("asset_key", "content_sha256", "availability")}
            for asset in assets
        ],
    }

    transcript.step = "read"
    world = _choose_saved_world(client.saved_worlds(), args)
    version = client.version(world["authored_version_id"], world_id=world["world_id"])
    if (world["authored_state_sha256"], world["authored_edit_seq"]) != (
        version["state_sha256"],
        version["edit_seq"],
    ):
        raise Stop(
            "the saved world's resume point is not its version's current state, so an edit bound "
            "to it would be refused; open the saved world in the app to reconcile it first"
        )
    print(
        f"saved world {world['title']!r} opens at version {version['version_id']}, state "
        f"{version['state_sha256'][:12]}, {len(version['objects'])} object(s)"
    )
    outcome["saved_world_before"] = _entry_summary(world)
    outcome["version_before"] = _version_summary(version)

    asset = _choose_asset(assets, args.asset_key)
    behaviour = _choose_behaviour(behaviours, args.behaviour)
    parameters = _parameters(behaviour, args.parameter)
    x, y, z = args.place
    transform = {
        "x_mm": x,
        "y_mm": y,
        "z_mm": z,
        "yaw_microradians": UPRIGHT_YAW_MICRORADIANS,
        "scale_milli": REVIEWED_SIZE_SCALE_MILLI,
    }
    region = _region(world, version, args.region)
    object_id = args.object_id or f"developer-client:{secrets.token_hex(4)}"

    transcript.step = "place"
    placed = client.place_object(
        version,
        object_id=object_id,
        asset_sha256=asset["content_sha256"],
        region_id=region,
        transform=transform,
        origin_role=args.origin_role,
        saved_entry=world,
    )
    world = client.saved_world(world["entry_id"])

    transcript.step = "motion"
    chosen = {
        "behaviour_key": behaviour.key,
        "behaviour_version": behaviour.version,
        "parameters": parameters,
    }
    moving = client.set_behaviour(placed, object_id, chosen, saved_entry=world)
    world = client.saved_world(world["entry_id"])
    outcome["edits"] = [
        {
            "edit": "place_object",
            "object_id": object_id,
            "asset_key": asset["asset_key"],
            "region_id": region,
            "transform": transform,
            "origin_role": args.origin_role,
            "base_state_sha256": version["state_sha256"],
            "result_state_sha256": placed["state_sha256"],
        },
        {
            "edit": "set_object_behaviour",
            "object_id": object_id,
            "behaviour": chosen,
            "base_state_sha256": placed["state_sha256"],
            "result_state_sha256": moving["state_sha256"],
        },
    ]

    transcript.step = "unsupported"
    unlisted = {**chosen, "behaviour_version": _unlisted_version(behaviours, behaviour.key)}
    try:
        client.set_behaviour(moving, object_id, unlisted, saved_entry=world)
    except ApiRefusal as refused:
        outcome["refusal"] = {
            "request": {"object_id": object_id, "behaviour": unlisted},
            "reason_unsupported": (
                f"{behaviour.key}@{unlisted['behaviour_version']} is not in the server's "
                f"behaviour registry, which lists {', '.join(b.identity for b in behaviours)}"
            ),
            "status": refused.status,
            "code": refused.code,
            "detail": refused.detail,
        }
        print(f"refused as it should be: {refused.status} {refused.code}: {refused.detail}")
    else:
        raise Stop(f"the server accepted {behaviour.key}@{unlisted['behaviour_version']}")

    transcript.step = "confirm"
    fresh = client.version(version["version_id"], world_id=version["world_id"])
    reopened = client.saved_world(world["entry_id"])
    outcome["version_after"] = _version_summary(fresh)
    outcome["saved_world_after"] = _entry_summary(reopened)
    outcome["checks"] = _checks(fresh, reopened, moving, asset, object_id, transform, args, chosen)


def _checks(
    fresh: Mapping[str, Any],
    reopened: Mapping[str, Any],
    moving: Mapping[str, Any],
    asset: Mapping[str, Any],
    object_id: str,
    transform: Mapping[str, int],
    args: argparse.Namespace,
    chosen: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Every fact the edits claimed, compared with what a fresh read says. Each names both sides."""
    obj = _find(fresh, object_id) or {}
    placed_at = {key: obj.get("transform", {}).get(key) for key in transform}
    last_two = [(e["kind"], e["object_id"]) for e in fresh["edits"][-2:]]
    facts: list[tuple[str, object, object]] = [
        ("the object is in the version and not removed", True, bool(obj) and not obj["removed"]),
        (
            "it is made from the chosen reviewed asset",
            asset["content_sha256"],
            obj.get("asset", {}).get("content_sha256"),
        ),
        ("its bytes are available to draw", "available", obj.get("asset", {}).get("availability")),
        ("it stands where it was placed", dict(transform), placed_at),
        (
            "its origin is the role the person chose",
            {"kind": "authored", "role": args.origin_role},
            obj.get("origin"),
        ),
        ("it carries the motion that was set", dict(chosen), obj.get("behaviour")),
        (
            "the version's state is the one the motion edit answered with, so the refused request "
            "changed nothing",
            moving["state_sha256"],
            fresh["state_sha256"],
        ),
        (
            "the newest two edits are this client's",
            [("add_object", object_id), ("set_object_behaviour", object_id)],
            last_two,
        ),
        (
            "the saved world reopens at that state",
            fresh["state_sha256"],
            reopened["authored_state_sha256"],
        ),
        ("the saved world reopens at that edit", fresh["edit_seq"], reopened["authored_edit_seq"]),
    ]
    return [
        {"check": name, "expected": expected, "observed": observed, "holds": expected == observed}
        for name, expected, observed in (
            (name, _plain(expected), _plain(observed)) for name, expected, observed in facts
        )
    ]


def _plain(value: object) -> object:
    """Tuples as lists, so a check compares what it will be written as."""
    return json.loads(json.dumps(value))


# -- the command line ------------------------------------------------------------------------------


def _millimetres(text: str) -> tuple[int, int, int]:
    """``x,y,z`` as three whole millimetres, the unit every authored transform is stored in."""
    parts = text.split(",")
    if len(parts) != 3 or not all(part.strip().lstrip("-").isdigit() for part in parts):
        raise argparse.ArgumentTypeError(f"{text!r} is not x,y,z in whole millimetres")
    x, y, z = (int(part) for part in parts)
    return x, y, z


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m exulanica_client", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("command", choices=("discover", "walkthrough"))
    parser.add_argument("--base-url", default=os.environ.get("EXULANICA_API_URL"))
    parser.add_argument(
        "--token-env",
        default="EXULANICA_TOKEN",
        help="environment variable holding the bearer token; it is never printed",
    )
    named = parser.add_mutually_exclusive_group()
    named.add_argument("--entry", help="the saved world's entry id")
    named.add_argument("--title", help="the saved world's title, which must be unique")
    parser.add_argument("--asset-key", help="the reviewed asset to place")
    parser.add_argument("--behaviour", help="KEY@VERSION of the reviewed behaviour to give")
    parser.add_argument(
        "--parameter",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="a behaviour parameter; the registry's default otherwise",
    )
    parser.add_argument("--region", help="the region to place into")
    parser.add_argument("--place", type=_millimetres, help="region-local x,y,z in millimetres")
    parser.add_argument(
        "--origin-role",
        choices=("fictional", "personal"),
        help="the person's choice; the server never infers it",
    )
    parser.add_argument("--object-id", help="the new object's id; a fresh one otherwise")
    parser.add_argument("--transcript", type=Path, help="write the transcript as JSON here")
    args = parser.parse_args(argv)
    if not args.base_url:
        parser.error("--base-url (or EXULANICA_API_URL) is required")
    if args.command == "walkthrough" and (args.place is None or args.origin_role is None):
        parser.error("walkthrough needs --place and --origin-role")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    token = os.environ.get(args.token_env, "")
    if not token:
        print(f"set {args.token_env} to a bearer token; it is never printed", file=sys.stderr)
        return _EXIT_USAGE
    transcript = Transcript()
    record: dict[str, Any] = {"command": args.command, "base_url": args.base_url}
    try:
        client = WorldClient(args.base_url, token, on_exchange=transcript.record)
        if args.command == "discover":
            transcript.step = "discover"
            _print_discovery(*discover(client))
            record["result"] = "discovered"
            code = _EXIT_CONFIRMED
        else:
            walkthrough(client, transcript, args, record)
            failed = [check["check"] for check in record["checks"] if not check["holds"]]
            record["result"] = "confirmed" if not failed else "not confirmed"
            for check in record["checks"]:
                print(f"  {'holds' if check['holds'] else 'FAILS'}: {check['check']}")
            code = _EXIT_CONFIRMED if not failed else _EXIT_STOPPED
    except (Stop, ApiRefusal, ClientError) as stopped:
        print(f"stopped: {stopped}", file=sys.stderr)
        record.update({"result": "stopped", "reason": str(stopped)})
        code = _EXIT_STOPPED
    record["exchanges"] = transcript.exchanges
    if args.transcript is not None:
        args.transcript.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"result: {record['result']}")
    return code
