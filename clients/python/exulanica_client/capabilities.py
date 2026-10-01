"""What a server says a caller can do with its worlds, read from the server and checked against it.

    EXULANICA_TOKEN=<token> python -m exulanica_client capabilities \\
        --base-url http://127.0.0.1:8000 [--exercise --origin-role fictional [--world WORLD_ID]] \\
        --transcript capabilities.json

Two reads answer it, each the server's own statement: ``GET /worlds/capabilities`` for making each
kind of world, and ``GET /world/versions/{version_id}/capabilities`` for the version each saved
world opens at. Every operation they name is a route (``"METHOD /path"``) with its state
(``available``, ``unavailable``, ``unsupported`` or ``unknown``), the code of any refusal, whether
this token may use it, the stale-base tokens its body carries and the reads that return them. This
module reads both for every saved world of the token's workspace and checks every route they name
against the OpenAPI document the same server serves, so a descriptor naming something the server
does not document is reported rather than trusted.

With ``--exercise`` it also makes a world of the run's own, of the first kind the creation read
calls available to this token: a starter in a workspace that holds no saved world, otherwise a
generated town. It makes one edit there, chosen from what the version read calls available rather
than from a list in this client: an arrangement, previewed and then applied, where one is available,
otherwise one reviewed object placed in a region the read lists. The edit is bound to the new
world's saved entry, so that world opens where the edit left it. It then sends the same request
again, unbound, against the base it has just replaced, which the server must refuse by name; reads
the base again from the read the descriptor names; and checks that every saved world that was there
before the run is as it was. With ``--world`` it edits that existing world instead, unbound, and
says so: that saved world opens again only once its new version is adopted.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from .client import WorldClient, resume_point

__all__ = [
    "CREATION",
    "EXERCISE_TITLE",
    "descriptor_checks",
    "documented_routes",
    "exercise",
    "exercise_run",
    "make_world",
    "print_capabilities",
    "read_capabilities",
]

CREATION = "/worlds/capabilities"
_STATES = ("available", "unavailable", "unsupported", "unknown")
_PLACE = "POST /world/versions/{version_id}/objects"
_PREVIEW_ARRANGEMENT = "POST /world/versions/{version_id}/arrangements/preview"
_APPLY_ARRANGEMENT = "POST /world/versions/{version_id}/arrangements/apply"
#: A placed object faces its region's own axes at its reviewed size.
_UPRIGHT = {"yaw_microradians": 0, "scale_milli": 1000}
#: The creation routes an exercise makes its own world with, in the order it tries them, and the
#: body each takes. A world from photographs needs photographs this client does not have.
_MAKERS = ("POST /world-entries/starter", "POST /worlds/generated")
#: The title of the world an exercise makes.
EXERCISE_TITLE = "Developer client exercise"


def read_capabilities(client: WorldClient) -> dict[str, Any]:
    """Both reads: making worlds, and each saved world's version."""
    worlds = [_world(client, entry) for entry in client.saved_worlds()]
    return {"creation": client.get(CREATION), "worlds": worlds}


def _world(client: WorldClient, entry: Mapping[str, Any]) -> dict[str, Any]:
    """One saved world as the reads describe it: its entry and its version's capabilities."""
    return {
        "entry_id": entry["entry_id"],
        "title": entry["title"],
        "world_id": entry["world_id"],
        "source_kind": entry["source_kind"],
        "capabilities": client.get(
            "/world/versions/"
            + urllib.parse.quote(entry["authored_version_id"], safe="")
            + "/capabilities",
            query={"world_id": entry["world_id"]},
        ),
    }


def documented_routes(openapi: Mapping[str, Any]) -> set[str]:
    """Every ``"METHOD /path"`` the server's OpenAPI document declares."""
    return {
        f"{method.upper()} {path}"
        for path, item in openapi.get("paths", {}).items()
        for method in item
        if method.lower() in ("get", "put", "post", "patch", "delete")
    }


def _descriptors(read: Mapping[str, Any]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    for kind in read["creation"]["kinds"]:
        if kind.get("create") is not None:
            yield f"making a {kind['kind']} world", kind["create"]
    for world in read["worlds"]:
        for descriptor in world["capabilities"]["operations"]:
            yield f"{world['title']!r}", descriptor


def descriptor_checks(openapi: Mapping[str, Any], read: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Each descriptor held to the server's own document and to the states the contract allows."""
    routes = documented_routes(openapi)
    checks = []
    for where, descriptor in _descriptors(read):
        named = [descriptor["operation"]]
        named += [base["read"] for base in descriptor["base"]]
        named += list(descriptor["options"])
        if descriptor["preview"] is not None:
            named.append(descriptor["preview"]["operation"])
        if descriptor["subjects"] is not None:
            named.append(descriptor["subjects"]["read"])
        undocumented = sorted(route for route in named if route not in routes)
        state, code = descriptor["state"], descriptor["code"]
        if state == "available":
            coded = code is None
        elif state in ("unavailable", "unsupported"):
            coded = code is not None
        else:
            coded = state == "unknown"
        checks.append(
            {
                "check": f"{where}: {descriptor['operation']} names only documented routes and a "
                "state the contract allows",
                "holds": not undocumented and coded,
                "undocumented": undocumented,
                "state": state,
                "code": code,
            }
        )
    return checks


def print_capabilities(read: Mapping[str, Any]) -> None:
    print("making worlds:")
    for kind in read["creation"]["kinds"]:
        create = kind["create"]
        state = "none" if create is None else _said(create)
        print(f"  {kind['kind']}: holds {kind['held']} of {kind['limit']}; create {state}")
    for world in read["worlds"]:
        capabilities = world["capabilities"]
        regions = capabilities["regions"]
        print(
            f"saved world {world['title']!r} ({capabilities['kind']}): regions "
            f"{', '.join(regions['region_ids']) or 'none'} ({regions['state']}); society "
            f"{capabilities['society']}"
        )
        for descriptor in capabilities["operations"]:
            bound = {k: v for k, v in descriptor["bind"].items() if k != "version_id"}
            print(f"  {descriptor['operation']} {bound or ''} {_said(descriptor)}".rstrip())


def _said(descriptor: Mapping[str, Any]) -> str:
    words = descriptor["state"] + (f" ({descriptor['code']})" if descriptor["code"] else "")
    if not descriptor["permitted"]:
        words += ", not permitted to this token"
    for effect in descriptor.get("effects", ()):
        if effect["state"] != "available":
            words += f"; {effect['on']}: {effect['state']} ({effect['code']})"
    return words


# -- one edit, chosen from what the read calls available ----------------------------------------


def _find(capabilities: Mapping[str, Any], operation: str) -> Mapping[str, Any] | None:
    return next(
        (d for d in capabilities["operations"] if d["operation"] == operation),
        None,
    )


def _usable(descriptor: Mapping[str, Any] | None) -> bool:
    return descriptor is not None and descriptor["state"] == "available" and descriptor["permitted"]


def _path(route: str, bind: Mapping[str, str]) -> tuple[str, str]:
    method, template = route.split(" ", 1)
    path = template
    for name, value in bind.items():
        path = path.replace("{" + name + "}", urllib.parse.quote(value, safe=""))
    return method, path


def _base(
    client: WorldClient,
    descriptor: Mapping[str, Any],
    world_id: str,
) -> dict[str, Any]:
    """Each base token the operation's body carries, read now from the read the descriptor names."""
    found = {}
    for base in descriptor["base"]:
        method, path = _path(base["read"], descriptor["bind"])
        assert method == "GET"
        found[base["field"]] = client.get(path, query={"world_id": world_id})[base["value"]]
    return found


def _arrangement(
    client: WorldClient,
    world: Mapping[str, Any],
    entry: Mapping[str, Any],
    applying: Mapping[str, Any],
    origin_role: str,
) -> dict[str, Any] | None:
    """An arrangement's body, previewed and shown ready; None when the preview does not show one
    ready where the person stands."""
    world_id = world["world_id"]
    catalog = client.get(_path(applying["options"][0], {})[1])
    chosen = catalog["arrangements"][0]
    region = (entry.get("authored_scene") or {}).get("region") or {}
    spawn = region.get("spawn") or {}
    body: dict[str, Any] = {
        "arrangement_key": chosen["key"],
        "arrangement_version": chosen["version"],
        "viewer": {
            "x_mm": spawn.get("x_mm", 0),
            "z_mm": spawn.get("z_mm", 0),
            "yaw_microradians": 3_141_593,
            "region_id": world["capabilities"]["regions"]["region_ids"][0],
        },
        "origin_role": origin_role,
        **_base(client, applying, world_id),
    }
    _, path = _path(applying["preview"]["operation"], applying["bind"])
    shown = client.post(path, body, query={"world_id": world_id})
    return body if shown.get("availability") == "ready" else None


def _placement(
    client: WorldClient, world: Mapping[str, Any], placing: Mapping[str, Any], origin_role: str
) -> dict[str, Any] | str:
    """One reviewed object, whose bytes this server holds, in the first region the read lists; or
    why no object can be placed."""
    if not world["capabilities"]["regions"]["region_ids"]:
        return "the read lists no region to place into"
    assets = client.get(_path(placing["options"][0], {})[1])
    asset = next((asset for asset in assets if asset["availability"] == "available"), None)
    if asset is None:
        return "the assets read lists no asset whose bytes this server holds"
    return {
        "object_id": "developer-client:capabilities",
        "asset_sha256": asset["content_sha256"],
        "region_id": world["capabilities"]["regions"]["region_ids"][0],
        "transform": {"x_mm": 0, "y_mm": 0, "z_mm": 0, **_UPRIGHT},
        "origin_role": origin_role,
        **_base(client, placing, world["world_id"]),
    }


def exercise(
    client: WorldClient,
    world: Mapping[str, Any],
    entry: Mapping[str, Any],
    *,
    origin_role: str,
    bind: bool,
    step: Callable[[str], None] = lambda _name: None,
) -> dict[str, Any]:
    """One available edit in ``world``: an arrangement previewed first where one is available and
    shows ready, else one reviewed object placed; applied; sent again against the base it replaced
    to be refused; and its base read again. With ``bind`` the edit is bound to the saved world's
    entry, as the walkthrough's edits are, and the saved world is read again: it must still open
    where the edit left it. Returns what happened."""
    capabilities = world["capabilities"]
    world_id = world["world_id"]
    applying = _find(capabilities, _APPLY_ARRANGEMENT)
    placing = _find(capabilities, _PLACE)
    record: dict[str, Any] = {"world": world["title"], "kind": capabilities["kind"]}
    body = None
    descriptor = None
    if _usable(applying) and applying is not None:
        step("preview")
        body = _arrangement(client, world, entry, applying, origin_role)
        descriptor = applying if body is not None else None
        record["preview"] = "ready" if body is not None else "not ready where the person stands"
    if body is None and _usable(placing) and placing is not None:
        placed = _placement(client, world, placing, origin_role)
        if isinstance(placed, str):
            record["result"] = f"no object can be placed: {placed}"
            record["checks"] = [
                {
                    "check": f"{world['title']!r}: an edit the read calls available can be made",
                    "holds": False,
                }
            ]
            return record
        body, descriptor = placed, placing
    if body is None or descriptor is None:
        record["result"] = "no edit is available to this token in this world"
        record["checks"] = []
        return record
    # Bound, the saved world advances with the edit, or neither does; unbound, the saved world
    # opens again only once its new version is adopted. A preview writes nothing and takes none.
    bound = {**body, "saved_entry": resume_point(entry)} if bind else body
    step("apply")
    method, path = _path(descriptor["operation"], descriptor["bind"])
    applied = client.post(path, bound, query={"world_id": world_id})
    record["applied"] = descriptor["operation"]
    step("stale")
    # Sent again unbound, so the version's own base token, the one the descriptor names, is what
    # refuses it; a bound copy is refused first by the saved world's resume point.
    status, refused = client.request(method, path, query={"world_id": world_id}, body=body)
    problem = refused if isinstance(refused, dict) else {}
    record["stale"] = {
        "status": status,
        "code": problem.get("code"),
        "detail": problem.get("detail"),
    }
    step("reread")
    reread = _base(client, descriptor, world_id)
    answered = applied.get("version", applied)
    record["checks"] = [
        {
            "check": f"{world['title']!r}: the same request against the replaced base is refused "
            "by name",
            "holds": status == 409 and bool(problem.get("code")),
        },
        {
            "check": f"{world['title']!r}: the base read again is the one the accepted edit "
            "answered with",
            "holds": reread.get("base_state_sha256") == answered.get("state_sha256"),
        },
    ]
    if bind:
        resumed = client.saved_world(entry["entry_id"])
        record["checks"].append(
            {
                "check": f"{world['title']!r}: the saved world still opens where the edit left it",
                "holds": resumed.get("availability") == "available",
            }
        )
    return record


def make_world(
    client: WorldClient, creation: Mapping[str, Any], *, title: str = EXERCISE_TITLE
) -> tuple[dict[str, Any] | None, list[str]]:
    """A world of this run's own, made by the first route in ``_MAKERS`` the creation read calls
    available to this token. Returns its saved entry as the entries read serves it, or None, and
    why each route it passed over was not used."""
    creates = {
        row["create"]["operation"]: row["create"]
        for row in creation["kinds"]
        if row["create"] is not None
    }
    passed: list[str] = []
    for route in _MAKERS:
        create = creates.get(route)
        if not _usable(create) or create is None:
            passed.append(f"{route}: {_said(create) if create else 'not offered'}")
            continue
        body: dict[str, Any] = {"title": title}
        if route == "POST /worlds/generated":
            # The first recipe the read the descriptor names lists.
            body["recipe"] = client.get(_path(create["options"][0], {})[1])[0]["key"]
        made = client.post(_path(route, create["bind"])[1], body)
        return client.saved_world(made["entry_id"]), passed
    return None, passed


def exercise_run(
    client: WorldClient,
    read: Mapping[str, Any],
    *,
    origin_role: str,
    world_id: str | None = None,
    step: Callable[[str], None] = lambda _name: None,
) -> dict[str, Any]:
    """The exercise: in a world this run makes, touching no other saved world; or, when
    ``world_id`` names one, in that existing world, unbound, with a warning that says so."""
    entries = {entry["entry_id"]: entry for entry in client.saved_worlds()}
    if world_id is not None:
        world = next((w for w in read["worlds"] if w["world_id"] == world_id), None)
        if world is None:
            named = {"check": f"{world_id!r} is a saved world of this workspace", "holds": False}
            return {"made": None, "warning": None, "exercised": [], "checks": [named]}
        done = exercise(
            client,
            world,
            entries[world["entry_id"]],
            origin_role=origin_role,
            bind=False,
            step=step,
        )
        warning = (
            f"{world['title']!r} was edited outside its saved entry; it opens again only once its "
            "new version is adopted"
        )
        return {"made": None, "warning": warning, "exercised": [done], "checks": done["checks"]}
    step("make")
    made, passed = make_world(client, read["creation"])
    if made is None:
        none = {"check": "a world of this run's own was made: " + "; ".join(passed), "holds": False}
        return {"made": None, "warning": None, "exercised": [], "checks": [none]}
    done = exercise(
        client, _world(client, made), made, origin_role=origin_role, bind=True, step=step
    )
    after = {entry["entry_id"]: entry for entry in client.saved_worlds()}
    untouched = all(
        after.get(entry_id, {}).get("revision") == entry["revision"]
        and after.get(entry_id, {}).get("availability") == entry["availability"]
        for entry_id, entry in entries.items()
    )
    kept = {
        "check": f"each of the {len(entries)} saved worlds there before the run is as it was",
        "holds": untouched,
    }
    return {
        "made": {key: made[key] for key in ("entry_id", "world_id", "title", "source_kind")},
        "warning": None,
        "exercised": [done],
        "checks": [*done["checks"], kept],
    }
