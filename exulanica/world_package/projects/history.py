"""The read behind a project's history panel: checkpoints, changes, evidence, publication, versions.

Everything local is read exactly from the project folder's git history. Publication is read from
GitHub only when asked, and then whole or not at all. Which merge became which world version comes
from application records this folder committed when it applied them; merges applied from
elsewhere are not known here, and the read says so.
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from exulanica.world_package.projects.checkpoint import (
    ProjectError,
    checkpoint_digest,
    decode,
    evidence_digest,
    evidence_warnings,
)
from exulanica.world_package.projects.follow import FOLLOW_FILE, read_follow
from exulanica.world_package.projects.link import LINK_FILE, read_link
from exulanica.world_package.projects.publish import read_state
from exulanica.world_package.projects.repository import (
    DEPENDENCY_DIR,
    EVIDENCE_DIR,
    PROJECT_FILE,
    Project,
    published_through,
)
from exulanica.world_package.projects.summary import evidence_summary, report

PROFILE = "exulanica.world-project-history/v1"
APPLICATION_DIR = "applications"
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Application(BaseModel):
    """That a merged pull request became a world version: identities only, no world content."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    profile: Literal["exulanica.world-project-application/v1"]
    repository: Annotated[str, Field(pattern=r"^[A-Za-z0-9-]{1,100}/[A-Za-z0-9_.-]{1,100}$")]
    pull_request: Annotated[int, Field(ge=1)]
    merge_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    checkpoint_sha256: Digest
    evidence_sha256: dict[str, Digest]
    version_id: Annotated[str, Field(pattern=r"^[0-9a-f-]{36}$")]
    title: Annotated[str, Field(min_length=1, max_length=200)]


def application_document(value: Any) -> dict[str, Any]:
    try:
        return Application.model_validate(value).model_dump()
    except (ValidationError, ValueError) as exc:
        raise ProjectError("application record violates its closed schema") from exc


def record_application(project: Project, record: dict[str, Any]) -> dict[str, Any]:
    """Commit one application record; an identical record already present commits nothing."""
    document = application_document(record)
    name = f"{document['merge_commit']}.json"
    folder = project.folder / APPLICATION_DIR
    if folder.is_symlink() or (folder / name).is_symlink():
        raise ProjectError("application records must be regular files")
    data = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    path = folder / name
    if path.is_file() and path.read_bytes() == data:
        return {"committed": False, "reason": "unchanged"}
    folder.mkdir(exist_ok=True)
    path.write_bytes(data)
    text = (
        f"Record that pull request #{document['pull_request']} became world version "
        f"{document['version_id']}"
    )
    return {"committed": True, "commit": project._commit([f"{APPLICATION_DIR}/{name}"], text)}


def applications_at(project: Project, revision: str) -> list[dict[str, Any]]:
    listed = project.git("ls-tree", "--name-only", revision, f"{APPLICATION_DIR}/")
    records = []
    for path in listed.splitlines():
        if re.fullmatch(rf"{APPLICATION_DIR}/[0-9a-f]{{40}}\.json", path) is None:
            raise ProjectError("the applications folder holds an unexpected file")
        records.append(
            application_document(decode(project.git("show", f"{revision}:{path}").encode()))
        )
    return sorted(records, key=lambda r: (r["pull_request"], r["merge_commit"]))


def _automatic(project: Project) -> dict[str, Any] | None:
    """The folder's automatic publication: None where its link publishes by hand (or it has no
    link); else whether it is paused, why, and the attempts of the last day."""
    link = read_link(project.folder)
    if link is None or link.get("publish") != "automatic":
        return None
    state = read_state(project.folder)
    return {"paused": state["paused"], "attempts": state["attempts"]}


def _kind(project: Project, commit: str) -> str:
    """checkpoint (world, evidence or dependency files), link, follow or application, by what
    changed."""
    changed = set(
        project.git("show", "--name-only", "--format=", "--no-renames", commit).splitlines()
    )
    if changed == {LINK_FILE}:
        return "link"
    if changed == {FOLLOW_FILE}:
        return "follow"
    if changed and all(path.startswith(f"{APPLICATION_DIR}/") for path in changed):
        return "application"
    content = (PROJECT_FILE, f"{EVIDENCE_DIR}/", f"{DEPENDENCY_DIR}/")
    if any(path == PROJECT_FILE or path.startswith(content[1:]) for path in changed):
        return "checkpoint"
    return "other"


def history_read(
    project: Project,
    *,
    limit: int = 50,
    publication: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The whole history read. `publication` is a GitHub publication read, or None for none."""
    head = project.head()
    if head is None:
        raise ProjectError("project has no saved checkpoint")
    limit = max(1, min(limit, 500))
    lines = project.git("log", f"--max-count={limit + 1}", "--format=%H%x09%ct%x09%s").splitlines()
    entries = [line.split("\t", 2) for line in lines]
    states = [(project.at(c), project.sessions_at(c)) for c, _, _ in entries]
    records = applications_at(project, head)

    published_index: int | None = None
    oldest_first: list[str] = []
    publication_view: dict[str, Any] = {"state": "not read"}
    if publication is not None:
        history, start = published_through(project, publication["files"])
        oldest_first = [entry["commit"] for entry in history]
        published_index = start
        publication_view = {
            "state": "read",
            "repository": publication["repository"],
            "branch": publication["branch"],
            "branch_head": publication["branch_head"],
            "published_through": None if start is None or start < 0 else oldest_first[start],
            "matches_local_history": start is not None,
            "pull_request": publication["pull_request"],
        }

    checkpoints = []
    for index, (commit, seconds, message) in enumerate(entries[:limit]):
        world, sessions = states[index]
        older_world, older_sessions = states[index + 1] if index + 1 < len(states) else (None, {})
        kind = _kind(project, commit)
        warnings = {w["session"]: w["warning"] for w in evidence_warnings(world, sessions)}
        sessions_view = []
        for name, session in sorted(sessions.items()):
            before = {d["record_id"] for d in older_sessions.get(name, {}).get("decisions", [])}
            sessions_view.append(
                {
                    "file": f"{EVIDENCE_DIR}/{name}",
                    "session_id": session["session_id"],
                    "records": len(session["decisions"]),
                    "records_added": sum(
                        1 for d in session["decisions"] if d["record_id"] not in before
                    ),
                    "evidence_sha256": evidence_digest(session),
                    "warning": warnings.get(name),
                }
            )
        digest = checkpoint_digest(world)
        evidence = {name: evidence_digest(s) for name, s in sorted(sessions.items())}
        published = None
        if publication is not None:
            position = oldest_first.index(commit)
            published = published_index is not None and position <= published_index
        checkpoints.append(
            {
                "commit": commit,
                "committed_at_unix": int(seconds),
                "message": message,
                "kind": kind,
                "checkpoint_sha256": digest,
                "world_changes": report(older_world, world)["summary"],
                "evidence_changes": evidence_summary(older_sessions, sessions),
                "sessions": sessions_view,
                "published": published,
                "applied_as": [
                    {
                        "version_id": r["version_id"],
                        "title": r["title"],
                        "pull_request": r["pull_request"],
                        "merge_commit": r["merge_commit"],
                    }
                    for r in records
                    if kind == "checkpoint"
                    and r["checkpoint_sha256"] == digest
                    and r["evidence_sha256"] == evidence
                ],
            }
        )
    # A record applies to the newest content checkpoint holding exactly its content.
    seen: set[str] = set()
    for item in checkpoints:
        item["applied_as"] = [a for a in item["applied_as"] if a["merge_commit"] not in seen]
        seen.update(a["merge_commit"] for a in item["applied_as"])

    world, sessions = states[0]
    edited, edited_sessions = project.working(), project.working_sessions()
    return {
        "profile": PROFILE,
        "project_id": world["project_id"],
        "forked_from": world["forked_from"],
        "link": read_link(project.folder),
        # What the folder follows, as its follow file states it, or None where it follows none.
        "follow": read_follow(project.folder),
        # Whether the follower publishes it on its own, and why that is paused if it is.
        "automatic_publication": _automatic(project),
        "head": head,
        "pending": {
            "world": [] if edited == world else report(world, edited)["summary"],
            "evidence": evidence_summary(sessions, edited_sessions),
        },
        "checkpoints": checkpoints,
        "more": len(entries) > limit,
        "publication": publication_view,
        "applications": {
            "source": "this folder's records",
            "records": records,
            # Not matched to a listed checkpoint: older than the limit, or content since changed.
            "not_listed": [r["merge_commit"] for r in records if r["merge_commit"] not in seen],
        },
    }
