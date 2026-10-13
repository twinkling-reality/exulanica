"""Where a project folder publishes: a repository, a base branch and a project branch.

The link is a committed file in the project folder so it works offline, travels with the folder
and shows in its history. It holds no credential, token or URL; the GitHub CLI keeps the
account's authentication. Publication reads it in place of flags and refuses flags that disagree.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from exulanica.world_package.projects.checkpoint import MAX_BYTES, ProjectError, decode

LINK_FILE = "project-link.json"
PROFILE = "exulanica.world-project-link/v1"


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    profile: Literal["exulanica.world-project-link/v1"]
    repository: str
    base: str
    branch: str

    @model_validator(mode="after")
    def names(self) -> Link:
        from exulanica.world_package.projects.github import BranchTarget

        BranchTarget(self.repository, self.base, self.branch)
        return self


def make_link(repository: str, base: str, branch: str) -> dict[str, Any]:
    return link_document(
        {"profile": PROFILE, "repository": repository, "base": base, "branch": branch}
    )


def link_document(value: Any) -> dict[str, Any]:
    try:
        return Link.model_validate(value).model_dump()
    except (ValidationError, ValueError) as exc:
        raise ProjectError(
            "project link must name owner/repository and two distinct branches"
        ) from exc


def link_bytes(value: Any) -> bytes:
    return (json.dumps(link_document(value), indent=2, sort_keys=True) + "\n").encode()


def read_link(folder: Path) -> dict[str, Any] | None:
    path = folder / LINK_FILE
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise ProjectError("project-link.json must be a regular file")
    with path.open("rb") as stream:
        return link_document(decode(stream.read(MAX_BYTES + 1)))


def resolve(
    folder: Path, repository: str | None, base: str | None, branch: str | None
) -> dict[str, Any]:
    """The link, with any flag required to agree with it; flags alone when there is none."""
    linked = read_link(folder)
    given = {"repository": repository, "base": base, "branch": branch}
    if linked is None:
        if None in given.values():
            raise ProjectError(
                "this project has no link; link it or give --repository, --base and --branch"
            )
        return make_link(repository or "", base or "", branch or "")
    for key, value in given.items():
        if value is not None and value != linked[key]:
            raise ProjectError(f"--{key} differs from the project's link; change the link instead")
    return linked
