"""Where a world is kept: the state of each GitHub project that follows it, as its follower last
wrote it (``exulanica.world-project-status/v1``).

A world's project lives in a folder on the person's own computer, kept by its follower
(:mod:`exulanica.world_package.projects.follow`), and the HTTP surface may not import that package.
So the follower writes one small document beside each project it follows, `project-status.json`,
never committed and never published, and the server reads those documents here from the one
directory it is configured with (``EXULANICA_PROJECTS_DIRECTORY``, the directory the worker
follows); a hosted deployment configures none and keeps no project.

No value a caller sends becomes a path: :func:`read_every_status` lists the configured directory's
own folders and reads each one's status file (a regular file, never a link, bounded in size), and
:func:`read_statuses` keeps the ones that name the world asked about. A document holds no path,
token or credential; the one free text it holds is the pull request's title, which the project
wrote.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from exulanica.env import env_get

STATUS_FILE: Final = "project-status.json"
PROFILE: Final = "exulanica.world-project-status/v1"
#: The most bytes a status file may hold; a larger one is not read.
MAX_STATUS_BYTES: Final = 64 * 1024
#: The most project folders one read looks through.
MAX_FOLDERS: Final = 1_000

_Instant = Annotated[
    str, Field(pattern=r"^20[0-9]{2}-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z$")
]
_Id = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9:._/-]+$")]
_Repository = Annotated[
    str, Field(max_length=201, pattern=r"^[A-Za-z0-9-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Link(_Closed):
    repository: _Repository
    publish: Literal["automatic", "by hand"]


class PullRequest(_Closed):
    number: Annotated[int, Field(ge=1)]
    title: Annotated[str, Field(min_length=1, max_length=256)]


class Pause(_Closed):
    at: _Instant
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class GitHub(_Closed):
    """What the follower last read of the project's repository, and when."""

    read_at: _Instant
    #: PRIVATE, PUBLIC or INTERNAL, as GitHub states it; "unstated" where it states none.
    visibility: Literal["PRIVATE", "PUBLIC", "INTERNAL", "unstated"]
    #: Saved checkpoints the repository does not hold yet.
    not_sent: Annotated[int, Field(ge=0)]
    #: When the newest saved checkpoint the repository holds was saved, if it holds one: what was
    #: saved by then has reached GitHub, what was saved after it has not.
    sent_through_at: _Instant | None = None
    #: The open rolling pull request, if there is one.
    pull_request: PullRequest | None
    #: Why sending on its own is paused, where it is.
    paused: Pause | None
    #: Whether the last read reached GitHub at all.
    reached: bool


class ProjectStatus(_Closed):
    profile: Literal["exulanica.world-project-status/v1"]
    world_id: _Id
    version_id: _Id
    #: The project's own identity, by which a page asks for it to be put on GitHub; absent in a
    #: status written before the follower stated it.
    project_id: _Id | None = None
    written_at: _Instant
    #: Saved checkpoints in the project, and when the newest was saved.
    checkpoints: Annotated[int, Field(ge=0)]
    last_checkpoint_at: _Instant | None
    #: Whether changes are waiting to be saved (the world has not settled yet).
    pending: bool
    #: How long the world stays unchanged before its changes are saved (the follow's settle
    #: period), in whole seconds; absent in a status written before the follower stated it.
    settle_seconds: Annotated[int, Field(ge=1, le=86_400)] | None = None
    #: At most how many times a day the follower sends a linked project's changes on its own, as
    #: History's question to keep it on GitHub says it; absent in a status written before it.
    publications_per_day: Annotated[int, Field(ge=1, le=1_000)] | None = None
    link: Link | None
    github: GitHub | None


class StatusRefused(ValueError):
    """A status document that is not one, named without its values."""


def status_document(value: Any) -> dict[str, Any]:
    try:
        return ProjectStatus.model_validate(value).model_dump()
    except (ValidationError, ValueError) as exc:
        raise StatusRefused("a project status violates its closed schema") from exc


def write_status(folder: Path, value: Any) -> dict[str, Any]:
    """Replace a project folder's status whole, so a reader never sees half of it."""
    document = status_document(value)
    data = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(dir=folder, prefix=".status-", suffix=".json")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, folder / STATUS_FILE)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return document


def projects_directory(environ: Mapping[str, str] | None = None) -> Path | None:
    """The directory this instance reads project states from, or None where it keeps none."""
    value = env_get("PROJECTS_DIRECTORY", environ)
    return None if value is None else Path(value)


def _read(path: Path) -> dict[str, Any] | None:
    """One folder's status, or None where it has none that reads."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        with path.open("rb") as stream:
            data = stream.read(MAX_STATUS_BYTES + 1)
        if len(data) > MAX_STATUS_BYTES:
            return None
        return status_document(json.loads(data))
    except (OSError, ValueError):
        return None


def read_every_status(directory: Path | None) -> list[dict[str, Any]]:
    """The status of every project in `directory`, whatever world it follows, newest written first.

    Only the directory's own folders are read (never a link, never a path a caller names); a
    folder whose status is missing, too large or not a status document is passed over."""
    if directory is None or directory.is_symlink() or not directory.is_dir():
        return []
    found = []
    try:
        folders = sorted(directory.iterdir())[:MAX_FOLDERS]
    except OSError:
        return []
    for folder in folders:
        if folder.name.startswith(".") or folder.is_symlink() or not folder.is_dir():
            continue
        status = _read(folder / STATUS_FILE)
        if status is not None:
            found.append(status)
    return sorted(found, key=lambda status: status["written_at"], reverse=True)


def read_statuses(directory: Path | None, world_id: str) -> list[dict[str, Any]]:
    """The status of every project in `directory` that follows `world_id`, newest written first,
    read as :func:`read_every_status` reads them."""
    return [status for status in read_every_status(directory) if status["world_id"] == world_id]
