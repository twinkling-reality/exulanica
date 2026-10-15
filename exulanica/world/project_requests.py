"""A person's request to keep a world in a project (``exulanica.world-project-request/v1``): the
server writes it, the world's follower takes it.

Keeping a world in a project needs a folder on the person's own computer, made and followed by the
follower (:mod:`exulanica.world_package.projects.follow`), which the HTTP surface may not import.
So a request is one small document the server writes into the projects directory it is configured
with (``EXULANICA_PROJECTS_DIRECTORY``, the directory the follower follows), in its `.requests`
folder, which no project folder can be (the follower passes over dot-folders). The follower takes
each request on its next scan: it makes a project folder it names itself, starts the project as
following a world does, and removes the request, or marks it refused by a code a page says.

No value a caller sends becomes a path. A request's file is named by the identity the server gives
it (32 hexadecimal characters) and lies in the requests folder alone, which is a real folder,
never a link; a request a caller names is found by that identity, checked against the same
pattern, and only for the world asked about in the caller's own workspace (one install may hold
worlds of several workspaces under one id). A document holds identities, a setting and times,
never a path, token or word a person wrote.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import tempfile
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROFILE: Final = "exulanica.world-project-request/v1"
#: The folder in the projects directory requests are written in; a dot-folder, so never a project.
REQUESTS_FOLDER: Final = ".requests"
#: The lock every change to the requests folder holds (the server's and the follower's), so two
#: asks for one world never both write.
LOCK_FILE: Final = ".lock"
#: The most bytes a request file may hold; a larger one is not read.
MAX_REQUEST_BYTES: Final = 4 * 1024
#: The most requests the folder holds at once; another is refused until the follower takes some.
MAX_REQUESTS: Final = 256
#: Why the follower could not start a project from a request, as a page words it.
REFUSALS: Final = ("nothing_to_keep", "world_unreadable", "too_many_projects", "failed")

_IDENTITY = re.compile(r"^[0-9a-f]{32}$")
_Identity = Annotated[str, Field(pattern=_IDENTITY.pattern)]
_Instant = Annotated[
    str, Field(pattern=r"^20[0-9]{2}-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z$")
]
_Id = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9:._/-]+$")]
_Workspace = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Refusal(_Closed):
    code: Literal["nothing_to_keep", "world_unreadable", "too_many_projects", "failed"]
    at: _Instant


class ProjectRequest(_Closed):
    profile: Literal["exulanica.world-project-request/v1"]
    request_id: _Identity
    #: The workspace that asked: one install may hold worlds of several workspaces under one id.
    workspace_id: _Workspace
    world_id: _Id
    version_id: _Id
    #: Whether the project keeps readable text (names and words a person wrote): such a project
    #: publishes only to a private repository.
    readable: bool
    requested_at: _Instant
    #: Why the follower could not start it; a refused request is replaced by the next one asked.
    refused: Refusal | None = None


class RequestRefused(ValueError):
    """A request that cannot be written, read or withdrawn here, named without its values."""


def request_document(value: Any) -> dict[str, Any]:
    try:
        return ProjectRequest.model_validate(value).model_dump()
    except (ValidationError, ValueError) as exc:
        raise RequestRefused("a project request violates its closed schema") from exc


def _instant(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _folder(directory: Path | None, *, make: bool = False) -> Path | None:
    """The requests folder of `directory`, a real folder never a link; None where there is none."""
    if directory is None or directory.is_symlink() or not directory.is_dir():
        return None
    folder = directory / REQUESTS_FOLDER
    if make and not folder.exists() and not folder.is_symlink():
        with contextlib.suppress(FileExistsError):
            folder.mkdir(mode=0o700)
    # A real folder, never a link: one there before, or one put there in between, is refused.
    if folder.is_symlink():
        raise RequestRefused("the projects directory's requests folder is a link")
    return folder if folder.is_dir() else None


@contextlib.contextmanager
def _locked(folder: Path) -> Iterator[None]:
    """Hold the requests folder's lock: one change at a time, from the server or the follower."""
    try:
        descriptor = os.open(folder / LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise RequestRefused("the requests folder's lock could not be opened") from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _path(folder: Path, request_id: str) -> Path:
    """A request's file, named by its identity alone: it cannot name another folder."""
    if _IDENTITY.fullmatch(request_id) is None:
        raise RequestRefused("a request is named by 32 hexadecimal characters")
    return folder / f"{request_id}.json"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        with path.open("rb") as stream:
            data = stream.read(MAX_REQUEST_BYTES + 1)
        if len(data) > MAX_REQUEST_BYTES:
            return None
        document = request_document(json.loads(data))
    except (OSError, ValueError):
        return None
    # A file is the request it is named for, or none.
    return document if path.name == f"{document['request_id']}.json" else None


def _write(folder: Path, document: dict[str, Any]) -> None:
    """Replace a request's file whole, so a reader never sees half of it."""
    data = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(dir=folder, prefix=".request-", suffix=".json")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, _path(folder, document["request_id"]))
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def read_requests(
    directory: Path | None, world: tuple[str, str] | None = None
) -> list[dict[str, Any]]:
    """The requests in `directory`'s requests folder, for one workspace's world where `world`
    names it (its workspace id and world id), oldest first. A file that is a link, too large,
    misnamed or not a request is passed over."""
    try:
        folder = _folder(directory)
        if folder is None:
            return []
        paths = sorted(folder.iterdir())[: MAX_REQUESTS * 2]
    except (OSError, RequestRefused):
        return []
    found = []
    for path in paths:
        if not path.name.endswith(".json") or _IDENTITY.fullmatch(path.name[:-5]) is None:
            continue
        document = _read(path)
        if document is not None and world in (None, _world_of(document)):
            found.append(document)
    return sorted(found, key=lambda document: (document["requested_at"], document["request_id"]))


def _world_of(document: dict[str, Any]) -> tuple[str, str]:
    return (document["workspace_id"], document["world_id"])


def request_project(
    directory: Path | None,
    *,
    workspace_id: str,
    world_id: str,
    version_id: str,
    readable: bool,
    now: datetime,
) -> dict[str, Any]:
    """Ask the follower to keep a version of one workspace's world in a project. A world has one
    request at a time: one still waiting is answered as it is; a refused one is replaced."""
    folder = _folder(directory, make=True)
    if folder is None:
        raise RequestRefused("no projects directory is configured here")
    with _locked(folder):
        held = read_requests(directory)
        for document in held:
            if _world_of(document) != (workspace_id, world_id):
                continue
            if document.get("refused") is None:
                return document
            _path(folder, document["request_id"]).unlink(missing_ok=True)
        if len(held) >= MAX_REQUESTS:
            raise RequestRefused("too many requests wait for the follower")
        document = request_document(
            {
                "profile": PROFILE,
                "request_id": uuid.uuid4().hex,
                "workspace_id": workspace_id,
                "world_id": world_id,
                "version_id": version_id,
                "readable": readable,
                "requested_at": _instant(now),
                "refused": None,
            }
        )
        _write(folder, document)
    return document


def withdraw_request(directory: Path | None, request_id: str, world: tuple[str, str]) -> bool:
    """Take back request `request_id` of one workspace's world (`world`: its workspace id and
    world id); False where that world has none such."""
    folder = _folder(directory)
    if folder is None:
        return False
    path = _path(folder, request_id)
    with _locked(folder):
        document = _read(path)
        if document is None or _world_of(document) != world:
            return False
        path.unlink(missing_ok=True)
    return True


def remove_request(directory: Path, request_id: str) -> None:
    """The follower took the request: it leaves the folder."""
    folder = _folder(directory)
    if folder is not None:
        with _locked(folder):
            _path(folder, request_id).unlink(missing_ok=True)


def refuse_request(directory: Path, request_id: str, code: str, now: datetime) -> None:
    """The follower could not start the project: the request stays, saying why by `code`."""
    folder = _folder(directory)
    if folder is None:
        return
    with _locked(folder):
        document = _read(_path(folder, request_id))
        if document is None:
            return
        refused = {"code": code, "at": _instant(now)}
        _write(folder, request_document({**document, "refused": refused}))
