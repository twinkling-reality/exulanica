"""Automatic publication: a followed project's rolling pull request follows it, when its owner
linked it so.

A project whose link says `publish: "automatic"` (:mod:`exulanica.world_package.projects.link`)
is published by the follower after each checkpoint it records, with the same two steps a person
runs: a review, which writes nothing, then a publication bound to the reviewed digest
(:class:`~exulanica.world_package.projects.github.RollingPullRequests`). Before every publication
the repository's visibility is read again and must say `PRIVATE`; a repository made public after
linking is not published to.

At most `per_day` attempts are made in any day; each is recorded before it is made, so a
follower that restarts keeps the bound. Anything refused or uncertain (a repository no longer
private, a rights refusal, a branch that moved, a step whose outcome is unknown) pauses automatic
publication for that project with its reason, and nothing is retried. A person's own successful
publication resumes it (:func:`resume`).

The state lives in `project-publish.json` (profile `exulanica.world-project-publish/v1`) beside
the project's files: written whole each time, never committed and never published, so it adds no
commit to what a pull request replays.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import Field, ValidationError

from exulanica.canonical import canonical_json
from exulanica.world_package.projects.checkpoint import MAX_BYTES, ProjectError, decode
from exulanica.world_package.projects.github import BranchTarget, RollingPullRequests
from exulanica.world_package.projects.schema import Closed, Instant, scan_values

PUBLISH_FILE: Final = "project-publish.json"
PROFILE: Final = "exulanica.world-project-publish/v1"
#: Automatic publications a day unless the follow file's limits state another number.
PUBLICATIONS_PER_DAY: Final = 24
DAY_SECONDS: Final = 86_400
#: The visibility that receives automatic publication.
PRIVATE: Final = "PRIVATE"


class Pause(Closed):
    at: Instant
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class PublishState(Closed):
    profile: Literal["exulanica.world-project-publish/v1"]
    #: When each automatic publication of the last day was attempted, oldest first.
    attempts: Annotated[list[Instant], Field(max_length=1_000)]
    paused: Pause | None


def _instant(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seconds(instant: str) -> float:
    return datetime.strptime(instant, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()


def state_document(value: Any) -> dict[str, Any]:
    try:
        document = PublishState.model_validate(value).model_dump()
        canonical_json(document)
        scan_values(document)
        return document
    except (ValidationError, ValueError) as exc:
        raise ProjectError("the publication state violates its closed schema") from exc


def read_state(folder: Path) -> dict[str, Any]:
    """The folder's publication state; none yet is no attempt and no pause."""
    path = folder / PUBLISH_FILE
    if not path.exists() and not path.is_symlink():
        return {"profile": PROFILE, "attempts": [], "paused": None}
    if path.is_symlink() or not path.is_file():
        raise ProjectError("project-publish.json must be a regular file")
    with path.open("rb") as stream:
        return state_document(decode(stream.read(MAX_BYTES + 1)))


def write_state(folder: Path, value: Any) -> dict[str, Any]:
    """Replace the state whole, so a reader never sees half of it."""
    document = state_document(value)
    data = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(dir=folder, prefix=".publish-", suffix=".json")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, folder / PUBLISH_FILE)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return document


def pause(folder: Path, reason: str, now: float) -> dict[str, Any]:
    state = read_state(folder)
    state["paused"] = {"at": _instant(now), "reason": reason[:500]}
    return write_state(folder, state)


def resume(folder: Path) -> bool:
    """Lift a pause after a person published by hand; True when there was one."""
    state = read_state(folder)
    if state["paused"] is None:
        return False
    write_state(folder, {**state, "paused": None})
    return True


def publish_automatically(
    project: Any,
    link: Mapping[str, Any],
    *,
    request: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    now: float,
    per_day: int = PUBLICATIONS_PER_DAY,
) -> dict[str, Any] | None:
    """Publish a project's last checkpoint to its rolling pull request, when its link says so.

    None when there is nothing to do (the link publishes by hand, or the pull request already
    holds the project); otherwise what happened: `published` with its actions, `held` when the
    day's attempts are spent (tried again after the next checkpoint), or `paused` with the reason.
    """
    if link.get("publish") != "automatic":
        return None
    folder = Path(project.folder)
    state = read_state(folder)
    if state["paused"] is not None:
        return {"state": "paused", "error": state["paused"]["reason"]}
    client = RollingPullRequests(request)
    target = BranchTarget(link["repository"], link["base"], link["branch"])
    try:
        review = client.review(target, project)
        # Read again on every review: a repository made public after linking gets nothing.
        if review["text"] != "readable":
            raise ProjectError(
                "the repository is no longer private, so nothing is published to it on its own"
            )
    except ProjectError as exc:
        return {"state": "paused", "error": pause(folder, str(exc), now)["paused"]["reason"]}
    if not review["actions"]:
        return None
    recent = [at for at in state["attempts"] if now - _seconds(at) < DAY_SECONDS]
    if len(recent) >= per_day:
        return {"state": "held", "error": f"at most {per_day} automatic publications a day"}
    # The attempt is recorded before it is made, so a restart keeps the bound.
    write_state(folder, {**state, "attempts": [*recent, _instant(now)]})
    try:
        result = client.publish(
            target,
            project,
            reviewed_sha256=review["review_sha256"],
            allow_publication=True,
        )
    except ProjectError as exc:
        return {"state": "paused", "error": pause(folder, str(exc), now)["paused"]["reason"]}
    except Exception as exc:
        # An outcome nobody can read is never retried: a person looks first.
        reason = f"publication stopped on {type(exc).__name__}; its outcome is unknown"
        return {"state": "paused", "error": pause(folder, reason, now)["paused"]["reason"]}
    return {"state": "published", "actions": result["actions"]}


def github_view(
    project: Any,
    link: Mapping[str, Any],
    *,
    request: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    now: float,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """What a project's repository holds of it, read once (GitHub reads only): its visibility,
    how many saved checkpoints it does not hold yet, the open rolling pull request, and a pause of
    sending on its own. Where GitHub cannot be read, the last view is kept and said unreached."""
    client = RollingPullRequests(request)
    target = BranchTarget(link["repository"], link["base"], link["branch"])
    paused = read_state(Path(project.folder))["paused"]
    try:
        remote = client.read(target)
        current = remote.branch_files if remote.branch_files is not None else remote.base_files
        # The commits a publication would make: what the repository does not hold yet.
        not_sent = len(client._steps(project, current, None))
    except ProjectError:
        held = dict(previous or {})
        return {
            "read_at": _instant(now),
            "visibility": held.get("visibility", "unstated"),
            "not_sent": held.get("not_sent", 0),
            "pull_request": held.get("pull_request"),
            "paused": paused,
            "reached": False,
        }
    visibility = remote.visibility
    pull = remote.pull_request
    return {
        "read_at": _instant(now),
        "visibility": visibility if visibility in ("PRIVATE", "PUBLIC", "INTERNAL") else "unstated",
        "not_sent": not_sent,
        "pull_request": None
        if pull is None
        else {"number": int(pull["number"]), "title": str(pull["title"])[:256] or "Changes"},
        "paused": paused,
        "reached": True,
    }
