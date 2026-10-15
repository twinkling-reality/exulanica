"""Apply a merged pull request's project to a running world as a new alternate version.

The new version is branched from the version the project was captured from, through the World
API's own routes, and titled with the repository, merge commit and pull request it came from.
Only placed things change: additions, moves and turns within a region, and removals. Model
assignments are reported for after the world is started, personalities are reported for the
world's owner to write, and evidence is never applied. The
source version is never edited, and nothing is written unless a bound review is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.world_package.projects.capture import WorldReader, segment
from exulanica.world_package.projects.checkpoint import Conflict, ProjectError, digest, document
from exulanica.world_package.projects.github import MergedPullRequest
from exulanica.world_package.projects.summary import movement
from exulanica.world_package.projects.words import model_name, names, possessive

POSE = ("x_mm", "y_mm", "z_mm", "yaw_microradians")


@dataclass(frozen=True)
class Edit:
    action: str  # add, move or remove
    thing_id: str
    body: dict[str, Any]
    sentence: str

    def view(self) -> dict[str, Any]:
        return {"action": self.action, "thing_id": self.thing_id, "body": self.body}


def title_for(merged: MergedPullRequest) -> str:
    return f"From {merged.repository} commit {merged.merge_commit} (pull request #{merged.number})"


def _pose(transform: dict[str, Any]) -> dict[str, int]:
    return {key: transform[key] for key in POSE}


def plan(world: dict[str, Any], version: dict[str, Any]) -> tuple[list[Edit], list[str], list[str]]:
    """The edits that make `version` hold the project's selected things, what is refused, and
    what is noted. Things the project never selected are left as they are."""
    edits: list[Edit] = []
    refused: list[str] = []
    notes: list[str] = []
    called = names([world])
    held = {thing["thing_id"]: thing for thing in version["things"]}
    for thing in sorted(world["things"], key=lambda t: t["thing_id"]):
        thing_id, name = thing["thing_id"], called[thing["thing_id"]]
        current = held.get(thing_id)
        if current is None:
            if thing["removed"]:
                notes.append(f"{name} is removed in the project and absent here; left absent")
                continue
            edits.append(
                Edit(
                    "add",
                    thing_id,
                    {
                        "thing_id": thing_id,
                        "kind": thing["kind"],
                        "region_id": thing["region_id"],
                        "pose": _pose(thing["transform"]),
                        "origin_role": thing["origin"]["role"],
                    },
                    f"add {name}",
                )
            )
            continue
        problems = [
            reason
            for wrong, reason in (
                (bool(current.get("gone")), "its kind is no longer available here"),
                (current["kind"] != thing["kind"], "changing what kind of thing it is"),
                (current["origin"] != thing["origin"], "changing its origin"),
                (current["region_id"] != thing["region_id"], "moving it to another region"),
                (current["removed"] and not thing["removed"], "restoring a removed thing"),
            )
            if wrong
        ]
        if problems:
            refused.extend(f"{name}: {reason} is not supported" for reason in problems)
            continue
        if _pose(current["transform"]) != _pose(thing["transform"]) and not thing["removed"]:
            words = movement(current["transform"], thing["transform"])
            edits.append(
                Edit(
                    "move",
                    thing_id,
                    {"pose": _pose(thing["transform"])},
                    f"move {name} {' and '.join(words)}" if words else f"turn {name}",
                )
            )
        if thing["removed"] and not current["removed"]:
            edits.append(Edit("remove", thing_id, {}, f"remove {name}"))
    order = {"remove": 0, "move": 1, "add": 2}
    edits.sort(key=lambda edit: (order[edit.action], edit.thing_id))
    return edits, refused, notes


def _versions(reader: WorldReader) -> list[dict[str, Any]]:
    listed = reader.json("GET versions", "/world/versions")
    if not isinstance(listed, list):
        raise ProjectError("world API returned malformed versions")
    return listed


def review(reader: WorldReader, merged: MergedPullRequest, base: str) -> dict[str, Any]:
    """What applying would do, bound to the versions as they read now. Writes nothing."""
    world = document(merged.world)
    if merged.base != base:
        raise Conflict("the pull request was merged into another branch than the project's base")
    if world["source"]["world_id"] != reader.world_id:
        raise Conflict("the project belongs to another world than this World API serves")
    title = title_for(merged)
    found = [
        v for v in _versions(reader) if v.get("title") == title and v["world_id"] == reader.world_id
    ]
    if len(found) > 1:
        raise Conflict("more than one version carries this merge's title; resolve it by hand")
    source_id = segment(world["source"]["version_id"])
    if found:
        target, mode = found[0], "resume"
    else:
        target = reader.json("GET version", f"/world/versions/{source_id}")
        mode = "branch"
        if target.get("source_invalidated"):
            raise Conflict("the project's source version is invalidated")
        if target["state_sha256"] != world["source"]["state_sha256"]:
            raise Conflict(
                "the world changed since this project was captured; capture it again and merge "
                "that instead"
            )
    edits, refused, notes = plan(world, target)
    called = names([world])
    for edit in edits:
        kind = edit.body.get("kind", {})
        if kind.get("source") == "workspace":
            try:
                reader.raw("GET thing kind", f"/things/kinds/{segment(kind['sha256'])}")
            except ProjectError:
                refused.append(f"{called[edit.thing_id]}: this workspace holds no such kind")
    pending = [
        f"change {possessive(called[model['thing_id']])} model to "
        f"{model_name(model['model_id'])} after the world is started"
        for model in world["models"]
    ]
    # Who a character is reaches its model's input, so it is never taken from a merge: the
    # world's owner writes it in the world.
    personalities = [
        f"write {possessive(called[character['thing_id']])} personality in the world"
        for character in world.get("characters") or []
    ]
    if refused:
        mode = "refused"
    elif not edits:
        mode = "already applied" if found else "nothing to apply"
    result = {
        "repository": merged.repository,
        "pull_request": merged.number,
        "merge_commit": merged.merge_commit,
        "title": title,
        "mode": mode,
        "source_version": world["source"]["version_id"],
        "target_version": target["version_id"] if found else None,
        "target_state_sha256": target["state_sha256"],
        "edits": [edit.view() for edit in edits],
        "changes": [edit.sentence for edit in edits],
        "refused": refused,
        "notes": notes,
        "not_applied": {
            "model_assignments": pending,
            "personalities": personalities,
            "evidence_sessions": sorted(merged.sessions),
        },
        "running_world_edited": False,
    }
    return {**result, "review_sha256": digest(canonical_json(result))}


def _write(reader: WorldReader, route: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    status, answer = reader.post(route, path, body)
    if status not in (200, 201) or not isinstance(answer, dict):
        code = answer.get("code") if isinstance(answer, dict) else None
        raise ProjectError(f"world API refused {route} with status {status} ({code or 'no code'})")
    return answer


def apply(
    reader: WorldReader,
    merged: MergedPullRequest,
    base: str,
    *,
    reviewed_sha256: str,
    allow_world_write: bool = False,
) -> dict[str, Any]:
    """Create the version (or resume it) and apply the reviewed edits, each CAS-chained."""
    if not allow_world_write:
        raise ProjectError("applying to a world requires explicit authorization")
    checked = review(reader, merged, base)
    if checked["review_sha256"] != reviewed_sha256:
        raise Conflict("the pull request or the world changed since the review; review again")
    if checked["mode"] in ("refused", "nothing to apply", "already applied"):
        return {"applied": False, "mode": checked["mode"], "refused": checked["refused"]}
    done: list[str] = []
    version_id = checked["target_version"]
    try:
        if version_id is None:
            created = _write(
                reader,
                "POST versions",
                "/world/versions",
                {"title": checked["title"], "parent_version_id": checked["source_version"]},
            )
            version_id = created["version_id"]
            done.append(f"created version {version_id}")
            edits, refused, _ = plan(document(merged.world), created)
            if refused or [e.view() for e in edits] != checked["edits"]:
                raise ProjectError(
                    "the new version did not inherit what the review saw; nothing was edited"
                )
            state = created["state_sha256"]
        else:
            state = checked["target_state_sha256"]
        version = segment(version_id)
        for edit in checked["edits"]:
            thing = segment(edit["thing_id"])
            path = {
                "add": f"/world/versions/{version}/things",
                "move": f"/world/versions/{version}/things/{thing}/move",
                "remove": f"/world/versions/{version}/things/{thing}/remove",
            }[edit["action"]]
            body = {"base_state_sha256": state, **edit["body"]}
            answer = _write(reader, f"POST {edit['action']} thing", path, body)
            state = answer["state_sha256"]
            done.append(f"{edit['action']} {edit['thing_id']}")
    except ProjectError as exc:
        raise ProjectError(
            f"apply stopped after {done or 'no step'}: {exc}. Review again; it resumes the "
            "version this merge's title names."
        ) from exc
    return {
        "applied": True,
        "version_id": version_id,
        "title": checked["title"],
        "steps": done,
        "state_sha256": state,
        "not_applied": checked["not_applied"],
        "running_world_edited": False,
    }
